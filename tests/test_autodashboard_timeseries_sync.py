from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tools.autodashboard_timeseries_sync import run


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class TestAutoDashboardTimeseriesSync(unittest.TestCase):
    def test_run_syncs_rows_into_autodashboard_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "session_timeseries.jsonl"
            target = root / "snapshots.jsonl"
            today = datetime.now().astimezone().date()
            yesterday = today - timedelta(days=1)

            _write_jsonl(
                source,
                [
                    {"snapshot_id": "wrapup:1", "kind": "wrapup", "date": yesterday.isoformat(), "ts": f"{yesterday.isoformat()}T18:30:00+09:00"},
                    {"snapshot_id": "codex:1", "kind": "codex_rollout", "date": today.isoformat(), "ts": f"{today.isoformat()}T09:00:00+09:00"},
                ],
            )

            result = run(
                {
                    "timeseries_file": str(source),
                    "autodashboard_file": str(target),
                    "days_back": 7,
                    "kinds": ["wrapup", "codex_rollout"],
                },
                {"workdir": str(root)},
            )

            rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "synced_file")
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["snapshot_id"], "wrapup:1")
        self.assertEqual(rows[1]["snapshot_id"], "codex:1")

    def test_run_skips_until_not_before_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "session_timeseries.jsonl"
            target = root / "snapshots.jsonl"
            today = datetime.now().astimezone().date()
            _write_jsonl(
                source,
                [
                    {"snapshot_id": "wrapup:1", "kind": "wrapup", "date": today.isoformat(), "ts": f"{today.isoformat()}T09:00:00+09:00"},
                ],
            )

            result = run(
                {
                    "timeseries_file": str(source),
                    "autodashboard_file": str(target),
                    "not_before_ts": "2999-01-01T18:30:00+09:00",
                },
                {"workdir": str(root)},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "skipped_not_before")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
