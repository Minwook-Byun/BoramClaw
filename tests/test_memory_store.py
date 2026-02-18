from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from main import format_memory_query_result, parse_memory_command
from memory_store import LongTermMemoryStore


class TestMemoryStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_memory"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_add_status_query_latest(self) -> None:
        case_root = self.runtime_root / "case1"
        case_root.mkdir(parents=True, exist_ok=True)
        store = LongTermMemoryStore(workdir=str(case_root), file_path="logs/memory.jsonl", max_records=10)
        store.add(session_id="s1", turn=1, role="U", text="딥시크 논문 요약해줘")
        store.add(session_id="s1", turn=1, role="A", text="딥시크 관련 arXiv 논문 3건을 요약했습니다.")
        status = store.status()
        self.assertEqual(status["records"], 2)
        hits = store.query("딥시크 논문", top_k=3)
        self.assertGreaterEqual(len(hits), 1)
        latest = store.latest(count=1)
        self.assertEqual(len(latest), 1)

    def test_parse_memory_command(self) -> None:
        self.assertEqual(parse_memory_command("/memory"), {"action": "status"})
        self.assertEqual(parse_memory_command("/memory status"), {"action": "status"})
        self.assertEqual(parse_memory_command("/memory latest 3"), {"action": "latest", "count": 3})
        query_cmd = parse_memory_command("/memory query 딥시크 논문")
        self.assertIsNotNone(query_cmd)
        assert query_cmd is not None
        self.assertEqual(query_cmd["action"], "query")
        self.assertIn("딥시크", query_cmd["text"])

    def test_format_memory_query_result(self) -> None:
        text = format_memory_query_result(
            "딥시크",
            [{"score": 0.88, "role": "A", "ts": "2026-02-18T00:00:00Z", "summary": "딥시크 관련 요약"}],
        )
        self.assertIn("메모리 검색 결과", text)
        self.assertIn("딥시크 관련 요약", text)

