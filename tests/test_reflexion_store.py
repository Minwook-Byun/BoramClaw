from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from main import parse_feedback_command, parse_reflexion_command
from reflexion_store import ReflexionStore, append_self_heal_feedback


class TestReflexionStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_reflexion"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_store_status_latest_query(self) -> None:
        case_root = self.runtime_root / self._testMethodName
        case_root.mkdir(parents=True, exist_ok=True)

        store = ReflexionStore(workdir=str(case_root), file_path="logs/reflexion_cases.jsonl", max_records=100)
        store.add_case(
            kind="tool_error:arxiv_daily_digest",
            input_text="딥시크 논문 3개",
            outcome="rate limit",
            fix="retry",
            source="tool",
            severity="error",
        )
        store.add_feedback(text="이상한 논문 가져오지 말아줘", source="user")

        status = store.status()
        self.assertEqual(status["records"], 2)
        self.assertGreaterEqual(status["types"].get("case", 0), 1)
        self.assertGreaterEqual(status["types"].get("feedback", 0), 1)

        latest = store.latest(count=2)
        self.assertEqual(len(latest), 2)

        queried = store.query("딥시크", top_k=3)
        self.assertGreaterEqual(len(queried), 1)

    def test_command_parsers(self) -> None:
        self.assertEqual(parse_reflexion_command("/reflexion"), {"action": "status"})
        self.assertEqual(parse_reflexion_command("/reflexion latest 3"), {"action": "latest", "count": 3})
        cmd = parse_reflexion_command("/reflexion query loop error")
        self.assertEqual(cmd, {"action": "query", "text": "loop error"})
        self.assertEqual(parse_feedback_command("/feedback 루프가 너무 짧음"), "루프가 너무 짧음")
        with self.assertRaises(ValueError):
            parse_feedback_command("/feedback")

    def test_append_self_heal_feedback(self) -> None:
        case_root = self.runtime_root / self._testMethodName
        case_root.mkdir(parents=True, exist_ok=True)
        append_self_heal_feedback(
            workdir=str(case_root),
            payload={"event": "user_feedback", "text": "테스트"},
            file_path="logs/self_heal_feedback.jsonl",
        )
        target = case_root / "logs" / "self_heal_feedback.jsonl"
        text = target.read_text(encoding="utf-8")
        self.assertIn("user_feedback", text)


if __name__ == "__main__":
    unittest.main()
