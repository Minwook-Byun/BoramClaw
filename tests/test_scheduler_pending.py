from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from scheduler import JobScheduler


class _FakeToolExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run_due_scheduled_jobs(self):
        return []

    def run_tool(self, name: str, input_data: dict):
        self.calls.append((name, input_data))
        if name == "fail_tool":
            return '{"error":"failed"}', True
        return '{"ok":true}', False


class TestSchedulerPending(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_scheduler_pending"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_heartbeat_executes_pending_tasks_and_clears_file(self) -> None:
        case_root = self.runtime_root / self._testMethodName
        case_root.mkdir(parents=True, exist_ok=True)
        pending = case_root / "pending.txt"
        pending.write_text(
            '\n'.join([
                '{"tool":"echo_tool","input":{"text":"hello"}}',
                'process_pending_task|{"task":"do something"}',
            ]) + '\n',
            encoding="utf-8",
        )
        fake = _FakeToolExecutor()
        heartbeat_payload: list[dict] = []
        scheduler = JobScheduler(
            poll_seconds=5,
            tool_executor=fake,
            on_heartbeat=lambda p: heartbeat_payload.append(p),
            pending_tasks_file=str(pending),
        )
        scheduler._heartbeat()

        self.assertEqual(len(fake.calls), 2)
        self.assertFalse(pending.exists())
        self.assertTrue(heartbeat_payload)
        self.assertEqual(heartbeat_payload[0].get("pending_ok"), 2)

    def test_heartbeat_keeps_failed_lines(self) -> None:
        case_root = self.runtime_root / self._testMethodName
        case_root.mkdir(parents=True, exist_ok=True)
        pending = case_root / "pending.txt"
        bad_line = '{"tool":"fail_tool","input":{}}'
        pending.write_text(bad_line + "\n", encoding="utf-8")

        fake = _FakeToolExecutor()
        scheduler = JobScheduler(
            poll_seconds=5,
            tool_executor=fake,
            pending_tasks_file=str(pending),
        )
        scheduler._heartbeat()

        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(pending.exists())
        self.assertIn("fail_tool", pending.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
