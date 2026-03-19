#!/usr/bin/env python3
"""
test_workday_recap.py
workday_recap 툴 테스트
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from workday_recap import TOOL_SPEC, run, _analyze_productivity, _build_timeline, _generate_summary


class TestToolSpec:
    def test_tool_spec_structure(self):
        assert TOOL_SPEC["name"] == "workday_recap"
        assert "description" in TOOL_SPEC
        assert "version" in TOOL_SPEC
        assert "input_schema" in TOOL_SPEC

    def test_input_schema_has_mode(self):
        props = TOOL_SPEC["input_schema"]["properties"]
        assert "mode" in props
        assert props["mode"]["enum"] == ["daily", "weekly"]

    def test_required_fields(self):
        required = TOOL_SPEC["input_schema"]["required"]
        assert "mode" in required


class TestSummaryAndTimeline:
    def test_generate_summary(self):
        report = {
            "mode": "daily",
            "sections": {
                "git": {"total_commits": 5},
                "shell": {"total_commands": 10},
                "browser": {"total_visits": 3},
            },
        }
        summary = _generate_summary(report)
        assert "오늘" in summary
        assert "커밋 5개" in summary
        assert "명령어 10개" in summary

    def test_timeline_includes_shell(self):
        report = {
            "sections": {
                "git": {"time_distribution": {10: 1}},
                "browser": {"time_distribution": {11: 2}},
                "shell": {"time_distribution": {"10:00": 3, "11:00": 1}},
            }
        }
        timeline = _build_timeline(report)
        assert timeline["hourly"][10]["git"] == 1
        assert timeline["hourly"][10]["shell"] == 3
        assert timeline["hourly"][11]["browser"] == 2
        assert timeline["hourly"][11]["shell"] == 1
        assert timeline["hourly"][10]["total"] == 4

    def test_productivity_analysis_shape(self):
        timeline = {
            "hourly": {h: {"git": 0, "browser": 0, "shell": 0, "total": 0} for h in range(24)}
        }
        timeline["hourly"][9]["total"] = 3
        timeline["hourly"][10]["total"] = 5
        timeline["hourly"][11]["total"] = 4
        analysis = _analyze_productivity(timeline)
        assert "peak_block" in analysis
        assert "morning_score" in analysis
        assert "focus_blocks" in analysis
        assert "context_switches" in analysis
        assert analysis["peak_block"]["total"] >= 0


class TestRunFunction:
    @patch("workday_recap._save_tomorrow_prediction")
    @patch("workday_recap._compare_with_predictions", return_value=None)
    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_daily_mode_success(
        self,
        mock_browser,
        mock_shell,
        mock_git,
        mock_screen,
        mock_compare,
        mock_save,
    ):
        mock_screen.return_value = {"ok": True, "results": []}
        mock_git.return_value = {
            "ok": True,
            "commits": [
                {
                    "date": "2026-02-20T10:00:00",
                    "message": "test",
                    "files": [{"status": "M", "file": "app.py"}],
                }
            ],
            "stats": {"files_changed": 1, "insertions": 5, "deletions": 2},
        }
        mock_shell.return_value = {
            "ok": True,
            "total_commands": 20,
            "unique_commands": 8,
            "top_commands": [{"command": "python3", "count": 8}],
            "time_distribution": {"10:00": 6},
            "alias_suggestions": [],
        }
        mock_browser.return_value = {
            "ok": True,
            "total_pages": 4,
            "unique_domains": 2,
            "top_domains": [{"domain": "example.com", "count": 2}],
            "domain_clusters": [],
            "time_sessions": [{"start_time": "2026-02-20T11:00:00", "page_count": 2}],
        }

        result = run({"mode": "daily", "scan_all_repos": False}, {})
        assert result["status"] == "success"
        report = result["report"]
        assert report["mode"] == "daily"
        assert "git" in report["sections"]
        assert "shell" in report["sections"]
        assert "browser" in report["sections"]
        assert "timeline" in report
        assert "productivity_analysis" in report
        assert "prediction_accuracy" in report
        assert report["prediction_accuracy"]["available"] is False
        assert report["timeline"]["hourly"][10]["shell"] == 6
        assert len(report["errors"]) == 0
        mock_compare.assert_called_once()
        mock_save.assert_called_once()

    @patch("workday_recap._summarize_weekly_feedback", return_value={"total_feedback": 0})
    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_weekly_mode(self, mock_browser, mock_shell, mock_git, mock_screen, mock_feedback):
        mock_screen.return_value = {"ok": True, "results": []}
        mock_git.return_value = {"ok": True, "commits": [], "stats": {}}
        mock_shell.return_value = {"ok": True, "total_commands": 0, "top_commands": [], "time_distribution": {}}
        mock_browser.return_value = {"ok": True, "total_pages": 0, "time_sessions": [], "domain_clusters": []}

        result = run({"mode": "weekly", "scan_all_repos": False}, {})

        assert result["status"] == "success"
        report = result["report"]
        assert report["mode"] == "weekly"
        assert report["period"] == "최근 7일"
        assert "feedback_learning" in report
        assert "prediction_accuracy" not in report
        mock_screen.assert_not_called()  # focus_keyword 없으면 screen 미실행
        mock_feedback.assert_called_once()

    @patch("workday_recap._save_tomorrow_prediction")
    @patch("workday_recap._compare_with_predictions", return_value=None)
    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_with_focus_keyword(
        self,
        mock_browser,
        mock_shell,
        mock_git,
        mock_screen,
        mock_compare,
        mock_save,
    ):
        mock_screen.return_value = {
            "ok": True,
            "results": [{"app_name": "Chrome", "content": {"text": "BoramClaw"}}],
        }
        mock_git.return_value = {"ok": True, "commits": [], "stats": {}}
        mock_shell.return_value = {"ok": True, "total_commands": 0, "top_commands": [], "time_distribution": {}}
        mock_browser.return_value = {"ok": True, "total_pages": 0, "time_sessions": [], "domain_clusters": []}

        result = run({"mode": "daily", "focus_keyword": "BoramClaw", "scan_all_repos": False}, {})
        assert result["status"] == "success"
        assert result["report"]["sections"]["screen"]["focus_keyword"] == "BoramClaw"
        call_args = mock_screen.call_args[0][0]
        assert call_args["query"] == "BoramClaw"

    @patch("workday_recap._save_tomorrow_prediction")
    @patch("workday_recap._compare_with_predictions", return_value=None)
    @patch("workday_recap.screen_search_run", side_effect=Exception("Network error"))
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_handles_exceptions(
        self,
        mock_browser,
        mock_shell,
        mock_git,
        mock_screen,
        mock_compare,
        mock_save,
    ):
        mock_git.return_value = {"ok": True, "commits": [], "stats": {}}
        mock_shell.return_value = {"ok": True, "total_commands": 0, "top_commands": [], "time_distribution": {}}
        mock_browser.return_value = {"ok": True, "total_pages": 0, "time_sessions": [], "domain_clusters": []}

        result = run({"mode": "daily", "focus_keyword": "err", "scan_all_repos": False}, {})
        assert result["status"] == "success"
        assert len(result["report"]["errors"]) > 0
        assert any("screen_search 예외" in err for err in result["report"]["errors"])


class TestCLI:
    def test_tool_spec_json_flag(self, capsys):
        from workday_recap import main

        with patch("sys.argv", ["workday_recap.py", "--tool-spec-json"]):
            main()

        captured = capsys.readouterr()
        spec = json.loads(captured.out)
        assert spec["name"] == "workday_recap"

    @patch("workday_recap._save_tomorrow_prediction")
    @patch("workday_recap._compare_with_predictions", return_value=None)
    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_cli_with_tool_input(
        self,
        mock_browser,
        mock_shell,
        mock_git,
        mock_screen,
        mock_compare,
        mock_save,
        capsys,
    ):
        mock_screen.return_value = {"ok": True, "results": []}
        mock_git.return_value = {"ok": True, "commits": [], "stats": {}}
        mock_shell.return_value = {"ok": True, "total_commands": 0, "top_commands": [], "time_distribution": {}}
        mock_browser.return_value = {"ok": True, "total_pages": 0, "time_sessions": [], "domain_clusters": []}

        from workday_recap import main

        input_json = json.dumps({"mode": "daily", "scan_all_repos": False})
        with patch("sys.argv", ["workday_recap.py", "--tool-input-json", input_json]):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
