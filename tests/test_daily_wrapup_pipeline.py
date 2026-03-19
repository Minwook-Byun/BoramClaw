from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tools.daily_wrapup_pipeline import run


def _run_git(repo: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "git command failed")


class TestDailyWrapupPipeline(unittest.TestCase):
    def test_run_generates_daily_wrapup_and_syncs_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "project"
            repo.mkdir()
            _run_git(repo, "init")
            _run_git(repo, "config", "user.name", "Boram")
            _run_git(repo, "config", "user.email", "boram@example.com")
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            _run_git(repo, "add", "README.md")
            _run_git(repo, "commit", "-m", "init")
            (repo / "main.py").write_text("print('wrapup')\n", encoding="utf-8")

            timeseries_file = root / "session_timeseries.jsonl"
            history_file = root / "history.jsonl"
            autodashboard_file = root / "snapshots.jsonl"
            retrospective_posts_file = root / "retrospective_posts.jsonl"
            retrospective_output_dir = root / "reviews"
            now = datetime.now().astimezone()
            history_file.write_text(
                "".join(
                    [
                        json.dumps(
                            {
                                "session_id": "session-1",
                                "ts": int(now.timestamp()) - 60,
                                "text": "오늘 회고를 길게 써줘",
                            },
                            ensure_ascii=False,
                        ),
                        "\n",
                        json.dumps(
                            {
                                "session_id": "session-1",
                                "ts": int(now.timestamp()),
                                "text": "아니 실제 구현된거랑 git도 보고 프롬프트 분석도 해줘",
                            },
                            ensure_ascii=False,
                        ),
                        "\n",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("tools.daily_wrapup_pipeline.is_codex_command_available", return_value=False):
                result = run(
                    {
                        "timeseries_file": str(timeseries_file),
                        "history_file": str(history_file),
                        "autodashboard_file": str(autodashboard_file),
                        "backfill_rollouts": False,
                        "retrospective_output_dir": str(retrospective_output_dir),
                        "retrospective_posts_file": str(retrospective_posts_file),
                        "retrospective_repo_roots": [str(repo)],
                    },
                    {"workdir": str(repo)},
                )

            rows = [json.loads(line) for line in timeseries_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            synced_rows = [json.loads(line) for line in autodashboard_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            retrospective_rows = [
                json.loads(line) for line in retrospective_posts_file.read_text(encoding="utf-8").splitlines() if line.strip()
            ]

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["wrapup_mode"], "fallback")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "wrapup")
        self.assertEqual(rows[0]["prompt_count"], 2)
        self.assertEqual(rows[0]["feedback_counts"]["corrected"], 1)
        self.assertEqual(rows[0]["touched_repos"][0]["name"], "project")
        self.assertEqual(len(synced_rows), 1)
        self.assertEqual(synced_rows[0]["snapshot_id"], rows[0]["snapshot_id"])
        self.assertEqual(retrospective_rows[0]["post_id"], f"daily_retrospective:{now.strftime('%Y-%m-%dT%H')}")


if __name__ == "__main__":
    unittest.main()
