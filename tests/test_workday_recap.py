#!/usr/bin/env python3
"""
test_workday_recap.py
workday_recap 툴 테스트
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from workday_recap import TOOL_SPEC, run, _generate_summary


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


class TestGenerateSummary:
    def test_daily_summary_with_commits(self):
        report = {
            "mode": "daily",
            "sections": {
                "git": {"total_commits": 5},
                "shell": {"total_commands": 10},
            },
        }
        summary = _generate_summary(report)
        assert "오늘" in summary
        assert "커밋 5개" in summary
        assert "명령어 10개" in summary

    def test_weekly_summary(self):
        report = {
            "mode": "weekly",
            "sections": {
                "browser": {"total_visits": 20},
            },
        }
        summary = _generate_summary(report)
        assert "이번 주" in summary
        assert "웹 방문 20개" in summary

    def test_empty_sections(self):
        report = {"mode": "daily", "sections": {}}
        summary = _generate_summary(report)
        assert "오늘 활동 데이터 없음" in summary


class TestRunFunction:
    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_daily_mode_success(self, mock_browser, mock_shell, mock_git, mock_screen):
        # Mock responses
        mock_screen.return_value = {
            "status": "success",
            "results": [{"app_name": "VS Code"}],
        }
        mock_git.return_value = {
            "status": "success",
            "summary": {"total_commits": 3, "authors": ["Alice"]},
        }
        mock_shell.return_value = {
            "status": "success",
            "analysis": {"total_commands": 50, "unique_commands": 20},
        }
        mock_browser.return_value = {
            "status": "success",
            "digest": {"total_visits": 10, "unique_domains": 5},
        }

        input_data = {"mode": "daily"}
        context = {}
        result = run(input_data, context)

        assert result["status"] == "success"
        report = result["report"]
        assert report["mode"] == "daily"
        assert "screen" in report["sections"]
        assert "git" in report["sections"]
        assert "shell" in report["sections"]
        assert "browser" in report["sections"]
        assert len(report["errors"]) == 0

    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_weekly_mode(self, mock_browser, mock_shell, mock_git, mock_screen):
        mock_screen.return_value = {"status": "success", "results": []}
        mock_git.return_value = {"status": "success", "summary": {}}
        mock_shell.return_value = {"status": "success", "analysis": {}}
        mock_browser.return_value = {"status": "success", "digest": {}}

        input_data = {"mode": "weekly"}
        context = {}
        result = run(input_data, context)

        assert result["status"] == "success"
        assert result["report"]["mode"] == "weekly"
        assert result["report"]["period"] == "최근 7일"

        # Check that functions were called with correct parameters
        mock_screen.assert_called_once()
        call_args = mock_screen.call_args[0][0]
        assert call_args["hours_back"] == 168  # 7 days

    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_with_focus_keyword(self, mock_browser, mock_shell, mock_git, mock_screen):
        mock_screen.return_value = {
            "status": "success",
            "results": [{"app_name": "Chrome", "content": {"text": "BoramClaw"}}],
        }
        mock_git.return_value = {"status": "success", "summary": {}}
        mock_shell.return_value = {"status": "success", "analysis": {}}
        mock_browser.return_value = {"status": "success", "digest": {}}

        input_data = {"mode": "daily", "focus_keyword": "BoramClaw"}
        context = {}
        result = run(input_data, context)

        assert result["status"] == "success"
        assert result["report"]["sections"]["screen"]["focus_keyword"] == "BoramClaw"

        # Check that screen_search was called with the keyword
        call_args = mock_screen.call_args[0][0]
        assert call_args["query"] == "BoramClaw"

    @patch("workday_recap.screen_search_run", side_effect=Exception("Network error"))
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_handles_exceptions(self, mock_browser, mock_shell, mock_git, mock_screen):
        mock_git.return_value = {"status": "success", "summary": {}}
        mock_shell.return_value = {"status": "success", "analysis": {}}
        mock_browser.return_value = {"status": "success", "digest": {}}

        input_data = {"mode": "daily"}
        context = {}
        result = run(input_data, context)

        assert result["status"] == "success"
        assert len(result["report"]["errors"]) > 0
        assert "screen_search 예외" in result["report"]["errors"][0]


class TestCLI:
    def test_tool_spec_json_flag(self, capsys):
        from workday_recap import main

        with patch("sys.argv", ["workday_recap.py", "--tool-spec-json"]):
            main()

        captured = capsys.readouterr()
        spec = json.loads(captured.out)
        assert spec["name"] == "workday_recap"

    @patch("workday_recap.screen_search_run")
    @patch("workday_recap.git_summary_run")
    @patch("workday_recap.shell_analyzer_run")
    @patch("workday_recap.browser_digest_run")
    def test_cli_with_tool_input(self, mock_browser, mock_shell, mock_git, mock_screen, capsys):
        mock_screen.return_value = {"status": "success", "results": []}
        mock_git.return_value = {"status": "success", "summary": {}}
        mock_shell.return_value = {"status": "success", "analysis": {}}
        mock_browser.return_value = {"status": "success", "digest": {}}

        from workday_recap import main

        input_json = json.dumps({"mode": "daily"})
        with patch("sys.argv", ["workday_recap.py", "--tool-input-json", input_json]):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
