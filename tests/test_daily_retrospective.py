from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from daily_retrospective import (
    append_retrospective_posts,
    build_daily_retrospective_markdown,
    build_retrospective_post,
    collect_daily_retrospective_evidence,
)


def _run_git(repo: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "git command failed")


class TestDailyRetrospective(unittest.TestCase):
    def test_collects_evidence_and_writes_post(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "demo"
            repo.mkdir()
            _run_git(repo, "init")
            _run_git(repo, "config", "user.name", "Boram")
            _run_git(repo, "config", "user.email", "boram@example.com")
            target_date = datetime.now().astimezone().date().isoformat()
            (repo / "app.py").write_text("print('demo')\n", encoding="utf-8")
            _run_git(repo, "add", "app.py")
            _run_git(repo, "commit", "-m", "feat: add demo")

            history_file = root / "history.jsonl"
            history_file.write_text(
                "".join(
                    [
                        json.dumps(
                            {
                                "session_id": "s1",
                                "ts": int(datetime.now().astimezone().timestamp()) - 60,
                                "text": "회고를 자동으로 포스팅도 되었으면 좋겠어",
                            },
                            ensure_ascii=False,
                        ),
                        "\n",
                        json.dumps(
                            {
                                "session_id": "s1",
                                "ts": int(datetime.now().astimezone().timestamp()),
                                "text": "아니 어제 기준으로 실제 구현된거랑 git도 보고 길게 써줘",
                            },
                            ensure_ascii=False,
                        ),
                        "\n",
                    ]
                ),
                encoding="utf-8",
            )

            evidence = collect_daily_retrospective_evidence(
                target_date=target_date,
                workdir=repo,
                history_file=history_file,
                sessions_root=root / "missing-sessions",
                repo_roots=[str(repo)],
            )
            markdown = build_daily_retrospective_markdown(evidence)
            post = build_retrospective_post(evidence=evidence, markdown=markdown)
            posts_file = root / "posts.jsonl"
            inserted = append_retrospective_posts(posts_file, [post])

            rows = [json.loads(line) for line in posts_file.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(evidence["prompt_count"], 2)
        self.assertEqual(evidence["history_prompt_count"], 2)
        self.assertEqual(evidence["feedback_counts"]["corrected"], 1)
        self.assertEqual(evidence["repo_activity"][0]["name"], "demo")
        self.assertEqual(evidence["primary_streams"][0]["repo_name"], "demo")
        self.assertIn("rollout 캡처가 비어", evidence["coverage_note"])
        self.assertIn("Daily Retrospective", markdown)
        self.assertIn("Coverage:", markdown)
        self.assertIn("레포별 실제 구현 흔적", markdown)
        self.assertIn("사용자 피드백 / 교정 신호", markdown)
        self.assertEqual(post["post_id"], f"daily_retrospective:{target_date}")
        self.assertEqual(post["feedback_counts"]["corrected"], 1)
        self.assertGreaterEqual(post["commit_count"], 1)
        self.assertGreaterEqual(post["delivery_commit_count"], 1)
        self.assertGreaterEqual(post["delivery_file_count"], 1)
        self.assertIn("coverage_note", post)
        self.assertIn("theme_totals", post)
        self.assertEqual(inserted, 1)
        self.assertEqual(rows[0]["post_id"], post["post_id"])

    def test_separates_generated_artifacts_from_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "ops-only"
            repo.mkdir()
            _run_git(repo, "init")
            _run_git(repo, "config", "user.name", "Boram")
            _run_git(repo, "config", "user.email", "boram@example.com")
            target_date = datetime.now().astimezone().date().isoformat()

            (repo / "logs").mkdir()
            (repo / "logs" / "watchdog.log").write_text("ok\n", encoding="utf-8")
            (repo / "logs" / "session_timeseries.jsonl").write_text("{}\n", encoding="utf-8")
            (repo / "cache").mkdir()
            (repo / "cache" / "posts.jsonl").write_text("{}\n", encoding="utf-8")

            history_file = root / "history.jsonl"
            history_file.write_text("", encoding="utf-8")

            evidence = collect_daily_retrospective_evidence(
                target_date=target_date,
                workdir=repo,
                history_file=history_file,
                sessions_root=root / "missing-sessions",
                repo_roots=[str(repo)],
            )
            markdown = build_daily_retrospective_markdown(evidence)
            post = build_retrospective_post(evidence=evidence, markdown=markdown)

        repo_row = evidence["repo_activity"][0]
        self.assertEqual(repo_row["delivery_touched_file_count"], 0)
        self.assertEqual(evidence["primary_streams"], [])
        self.assertEqual(post["delivery_commit_count"], 0)
        self.assertEqual(post["delivery_file_count"], 0)
        self.assertGreaterEqual(post["generated_file_count"], 1)
        self.assertGreaterEqual(post["ops_file_count"], 1)
        self.assertIn("운영 산출물 갱신 비중", markdown)


if __name__ == "__main__":
    unittest.main()
