from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from memory_store import LongTermMemoryStore


class TestMemoryVectorBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_memory_vector"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_sqlite_vector_backend_status_and_query(self) -> None:
        case_root = self.runtime_root / self._testMethodName
        case_root.mkdir(parents=True, exist_ok=True)

        store = LongTermMemoryStore(
            workdir=str(case_root),
            file_path="logs/memory.jsonl",
            vector_backend="sqlite",
            vector_db_path="logs/memory_vectors.sqlite",
            max_records=100,
        )
        store.add(session_id="s1", turn=1, role="U", text="딥시크 관련 논문을 찾아줘")
        store.add(session_id="s1", turn=2, role="A", text="딥시크 관련 arXiv 논문 3개를 요약했습니다")

        status = store.status()
        self.assertEqual(status.get("vector_backend"), "sqlite")
        self.assertGreaterEqual(int(status.get("vector_records", 0) or 0), 2)

        hits = store.query("딥시크 논문", top_k=5)
        self.assertGreaterEqual(len(hits), 1)
        self.assertIn("id", hits[0])

    def test_sqlite_vector_backend_persists_across_reload(self) -> None:
        case_root = self.runtime_root / self._testMethodName
        case_root.mkdir(parents=True, exist_ok=True)

        kwargs = {
            "workdir": str(case_root),
            "file_path": "logs/memory.jsonl",
            "vector_backend": "sqlite",
            "vector_db_path": "logs/memory_vectors.sqlite",
            "max_records": 100,
        }
        store1 = LongTermMemoryStore(**kwargs)
        store1.add(session_id="s1", turn=1, role="U", text="calendar 일정 확인")

        store2 = LongTermMemoryStore(**kwargs)
        hits = store2.query("일정", top_k=3)
        self.assertGreaterEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()
