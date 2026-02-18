from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest

from metrics_dashboard import build_dashboard_snapshot, render_dashboard_text


class TestMetricsDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_dashboard"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_build_snapshot_and_render(self) -> None:
        case_root = self.runtime_root / self._testMethodName
        logs_dir = case_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        token_rows = [
            {
                "ts": "2026-02-18T00:00:00+00:00",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "requests": 1,
                "estimated_cost_usd": 0.001,
            },
            {
                "ts": "2026-02-18T00:10:00+00:00",
                "input_tokens": 20,
                "output_tokens": 10,
                "total_tokens": 30,
                "requests": 2,
                "estimated_cost_usd": 0.002,
            },
        ]
        with (logs_dir / "token_usage.jsonl").open("w", encoding="utf-8") as fp:
            for row in token_rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        recovery_rows = [
            {"ts": "2026-02-18T00:00:00+00:00", "success": True},
            {"ts": "2026-02-18T00:05:00+00:00", "success": False},
        ]
        with (logs_dir / "recovery_metrics.jsonl").open("w", encoding="utf-8") as fp:
            for row in recovery_rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        with (logs_dir / "recovery_alerts.jsonl").open("w", encoding="utf-8") as fp:
            fp.write(json.dumps({"ts": "2026-02-18T00:06:00+00:00", "event": "alert"}, ensure_ascii=False) + "\n")

        chat_rows = [
            {
                "ts": "2026-02-18T00:00:00+00:00",
                "session_id": "s1",
                "event": "tool_call",
                "payload": json.dumps({"tool": "arxiv_daily_digest"}, ensure_ascii=False),
            },
            {
                "ts": "2026-02-18T00:01:00+00:00",
                "session_id": "s1",
                "event": "tool_call",
                "payload": json.dumps({"tool": "arxiv_daily_digest"}, ensure_ascii=False),
            },
            {
                "ts": "2026-02-18T00:02:00+00:00",
                "session_id": "s2",
                "event": "tool_call",
                "payload": json.dumps({"tool": "github_pr_digest"}, ensure_ascii=False),
            },
        ]
        with (logs_dir / "chat_log.jsonl").open("w", encoding="utf-8") as fp:
            for row in chat_rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        snapshot = build_dashboard_snapshot(
            workdir=str(case_root),
            chat_log_glob="logs/chat_log.jsonl",
        )
        self.assertEqual(snapshot["token_usage"]["requests"], 3)
        self.assertEqual(snapshot["token_usage"]["total_tokens"], 45)
        self.assertEqual(snapshot["recovery"]["records"], 2)
        self.assertEqual(snapshot["recovery"]["alerts"], 1)
        self.assertEqual(snapshot["chat"]["sessions"], 2)
        self.assertGreaterEqual(len(snapshot["chat"]["top_tools"]), 1)

        text = render_dashboard_text(snapshot)
        self.assertIn("운영 대시보드", text)
        self.assertIn("토큰/비용", text)
        self.assertIn("상위 도구 호출", text)


if __name__ == "__main__":
    unittest.main()
