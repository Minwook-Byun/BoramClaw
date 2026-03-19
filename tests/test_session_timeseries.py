from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from session_timeseries import append_timeseries_rows, build_wrapup_snapshot, render_period_svg, summarize_codex_rollout


class TestSessionTimeSeries(unittest.TestCase):
    def test_summarize_codex_rollout_collects_prompt_and_exec_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rollout_path = Path(td) / "rollout-2026-03-11T10-00-00-example.jsonl"
            rows = [
                {
                    "timestamp": "2026-03-11T01:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": "session-1", "cwd": "/Users/boram/project"},
                },
                {
                    "timestamp": "2026-03-11T01:00:01Z",
                    "type": "turn_context",
                    "payload": {
                        "model": "gpt-5.4",
                        "approval_policy": "on-request",
                        "sandbox_policy": {"type": "workspace-write"},
                    },
                },
                {
                    "timestamp": "2026-03-11T01:00:02Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "로그인 이슈 봐줘"},
                },
                {
                    "timestamp": "2026-03-11T01:00:03Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "A" * 140},
                },
                {
                    "timestamp": "2026-03-11T01:00:04Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "rg -n auth src", "workdir": "/Users/boram/project"}),
                    },
                },
                {
                    "timestamp": "2026-03-11T01:00:05Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "parallel",
                        "arguments": json.dumps(
                            {
                                "tool_uses": [
                                    {
                                        "recipient_name": "functions.exec_command",
                                        "parameters": {"cmd": "git status", "workdir": "/Users/boram/project"},
                                    }
                                ]
                            }
                        ),
                    },
                },
                {
                    "timestamp": "2026-03-11T01:00:06Z",
                    "type": "event_msg",
                    "payload": {"type": "agent_message", "phase": "commentary", "message": "checking"},
                },
                {
                    "timestamp": "2026-03-11T01:00:07Z",
                    "type": "response_item",
                    "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done"}]},
                },
            ]
            rollout_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

            snapshot = summarize_codex_rollout(rollout_path)

        self.assertEqual(snapshot["session_id"], "session-1")
        self.assertEqual(snapshot["user_prompt_count"], 2)
        self.assertEqual(snapshot["exec_command_count"], 2)
        self.assertEqual(snapshot["assistant_message_count"], 1)
        self.assertEqual(snapshot["commentary_count"], 1)
        self.assertEqual(snapshot["short_prompt_count"], 1)
        self.assertEqual(snapshot["long_prompt_count"], 1)
        self.assertEqual(snapshot["top_command_heads"][0]["command"], "rg")
        self.assertEqual(snapshot["top_workdirs"][0]["workdir"], "/Users/boram/project")
        self.assertEqual(snapshot["model"], "gpt-5.4")
        self.assertEqual(snapshot["approval_policy"], "on-request")
        self.assertEqual(snapshot["sandbox_mode"], "workspace-write")
        self.assertGreaterEqual(snapshot["theme_counts"].get("auth", 0), 1)

    def test_summarize_codex_rollout_tracks_feedback_signals(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rollout_path = Path(td) / "rollout-2026-03-11T11-00-00-example.jsonl"
            rows = [
                {
                    "timestamp": "2026-03-11T02:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": "session-feedback", "cwd": "/Users/boram/project"},
                },
                {
                    "timestamp": "2026-03-11T02:00:02Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "이번주 회고를 써줘"},
                },
                {
                    "timestamp": "2026-03-11T02:00:10Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "아니 어제 기준으로 실제 구현된거랑 git도 보고 다시 써줘"},
                },
                {
                    "timestamp": "2026-03-11T02:00:20Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "존댓말써!"},
                },
            ]
            rollout_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

            snapshot = summarize_codex_rollout(rollout_path)

        self.assertEqual(snapshot["feedback_prompt_count"], 2)
        self.assertEqual(snapshot["feedback_counts"]["corrected"], 2)
        self.assertEqual(snapshot["top_correction_hints"][0]["label"], "Git/로컬 근거 우선")

    def test_append_timeseries_rows_dedupes_snapshot_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "session_timeseries.jsonl"
            first = {"snapshot_id": "row-1", "ts": "2026-03-11T01:00:00+00:00", "kind": "wrapup"}
            second = {"snapshot_id": "row-1", "ts": "2026-03-11T01:05:00+00:00", "kind": "wrapup", "focus": "updated"}

            inserted_first = append_timeseries_rows(target, [first])
            inserted_second = append_timeseries_rows(target, [second])
            lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(inserted_first, 1)
        self.assertEqual(inserted_second, 0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["focus"], "updated")

    def test_build_wrapup_snapshot_tracks_memory_and_usage(self) -> None:
        snapshot = build_wrapup_snapshot(
            session_id="session-2",
            provider="codex",
            model="o3",
            focus="이번주 회고",
            answer="요약",
            session_memory=["user: 로그인 이슈 확인", "assistant: auth guard 수정"],
            usage={"input_tokens": 10, "output_tokens": 5, "requests": 1},
            ts=datetime(2026, 3, 12, 1, 0, 0, tzinfo=timezone.utc),
            snapshot_key="auto:2026-03-12",
            evidence={
                "prompt_count": 3,
                "prompt_samples": ["오늘 뭐 했지?", "자동 트리거 등도 붙여줘"],
                "feedback_prompt_count": 2,
                "feedback_counts": {
                    "accepted": 1,
                    "corrected": 1,
                    "retried": 0,
                    "ambiguous": 0,
                },
                "feedback_rates": {
                    "accepted": 0.5,
                    "corrected": 0.5,
                    "retried": 0.0,
                    "ambiguous": 0.0,
                },
                "top_correction_hints": [
                    {
                        "category": "evidence_first",
                        "label": "Git/로컬 근거 우선",
                        "count": 1,
                        "examples": ["실제로 구현된거랑 git도 보고"],
                    }
                ],
                "active_workdirs": ["/Users/boram/BoramClaw"],
                "touched_repos": [
                    {
                        "name": "BoramClaw",
                        "path": "/Users/boram/BoramClaw",
                        "branch": "main",
                        "modified_files": 4,
                        "untracked_files": 2,
                    }
                ],
                "git_totals": {
                    "repo_count": 1,
                    "modified_files": 4,
                    "untracked_files": 2,
                    "commit_count": 0,
                },
            },
        )

        self.assertEqual(snapshot["kind"], "wrapup")
        self.assertEqual(snapshot["snapshot_id"], "wrapup:auto:2026-03-12")
        self.assertEqual(snapshot["memory_entry_count"], 2)
        self.assertEqual(snapshot["user_memory_count"], 1)
        self.assertEqual(snapshot["assistant_memory_count"], 1)
        self.assertEqual(snapshot["usage"]["requests"], 1)
        self.assertEqual(snapshot["date"], "2026-03-12")
        self.assertEqual(snapshot["prompt_count"], 3)
        self.assertEqual(snapshot["feedback_prompt_count"], 2)
        self.assertEqual(snapshot["feedback_counts"]["corrected"], 1)
        self.assertEqual(snapshot["top_correction_hints"][0]["label"], "Git/로컬 근거 우선")
        self.assertEqual(snapshot["repo_count"], 1)
        self.assertEqual(snapshot["git_totals"]["modified_files"], 4)
        self.assertEqual(snapshot["prompt_samples"][0], "오늘 뭐 했지?")
        self.assertGreaterEqual(snapshot["theme_counts"].get("auth", 0), 1)

    def test_render_period_svg_writes_visual_file(self) -> None:
        rows = [
            {
                "snapshot_id": "codex:1",
                "kind": "codex_rollout",
                "date": "2026-03-10",
                "user_prompt_count": 10,
                "exec_command_count": 120,
                "duration_minutes": 45.0,
                "top_command_heads": [{"command": "sed", "count": 40}],
                "top_workdirs": [{"workdir": "/Users/boram/InnerPlatform-qa-p0", "count": 80}],
                "theme_counts": {"auth": 4, "ux_product": 2},
            },
            {
                "snapshot_id": "codex:2",
                "kind": "codex_rollout",
                "date": "2026-03-11",
                "user_prompt_count": 20,
                "exec_command_count": 240,
                "duration_minutes": 60.0,
                "top_command_heads": [{"command": "rg", "count": 60}],
                "top_workdirs": [{"workdir": "/Users/boram/InnerPlatform-ft-izzie-latest", "count": 90}],
                "theme_counts": {"evidence_drive": 8, "auth": 3},
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            svg_path = Path(td) / "review.svg"
            result = render_period_svg(rows, title="Weekly Review", output_path=svg_path)
            self.assertTrue(svg_path.exists())
            content = svg_path.read_text(encoding="utf-8")

        self.assertEqual(result["status"], "success")
        self.assertIn("<svg", content)
        self.assertIn("Weekly Review", content)
        self.assertIn("Daily prompts", content)
        self.assertIn("Theme totals", content)


if __name__ == "__main__":
    unittest.main()
