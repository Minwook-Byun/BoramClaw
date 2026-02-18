from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import threading
import time
import unittest

from config import BoramClawConfig
from gateway import RequestQueue
from logger import ChatLogger
from scheduler import JobScheduler
from tool_executor import PolicyToolExecutor


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run_tool(self, name: str, input_data: dict) -> tuple[str, bool]:
        self.calls.append((name, input_data))
        return json.dumps({"ok": True, "tool": name}), False

    def run_due_scheduled_jobs(self) -> list[dict]:
        return [{"job_id": "1", "status": "ok"}]


class TestModularArchitecture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_modular"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_config_permissions_map(self) -> None:
        old = os.environ.get("TOOL_PERMISSIONS_JSON")
        old_key = os.environ.get("ANTHROPIC_API_KEY")
        old_model = os.environ.get("CLAUDE_MODEL")
        old_workdir = os.environ.get("TOOL_WORKDIR")
        old_tools = os.environ.get("CUSTOM_TOOL_DIR")
        try:
            os.environ["TOOL_PERMISSIONS_JSON"] = '{"run_shell":"prompt","delete_custom_tool_file":"deny"}'
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
            os.environ["CLAUDE_MODEL"] = "claude-sonnet-4-5-20250929"
            os.environ["TOOL_WORKDIR"] = str(Path.cwd())
            os.environ["CUSTOM_TOOL_DIR"] = str(Path.cwd() / "tools")
            cfg = BoramClawConfig.from_env()
            perms = cfg.permissions_map()
            self.assertEqual(perms["run_shell"], "prompt")
            self.assertEqual(perms["delete_custom_tool_file"], "deny")
        finally:
            if old is None:
                os.environ.pop("TOOL_PERMISSIONS_JSON", None)
            else:
                os.environ["TOOL_PERMISSIONS_JSON"] = old
            if old_key is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old_key
            if old_model is None:
                os.environ.pop("CLAUDE_MODEL", None)
            else:
                os.environ["CLAUDE_MODEL"] = old_model
            if old_workdir is None:
                os.environ.pop("TOOL_WORKDIR", None)
            else:
                os.environ["TOOL_WORKDIR"] = old_workdir
            if old_tools is None:
                os.environ.pop("CUSTOM_TOOL_DIR", None)
            else:
                os.environ["CUSTOM_TOOL_DIR"] = old_tools

    def test_policy_tool_executor_deny_and_dry_run(self) -> None:
        base = FakeExecutor()
        executor = PolicyToolExecutor(
            base_executor=base,
            permissions={"run_shell": "deny", "echo_tool": "allow"},
            dry_run=True,
        )
        blocked_text, blocked_error = executor.run_tool("run_shell", {"command": "ls"})
        self.assertTrue(blocked_error)
        self.assertIn("차단", blocked_text)
        dry_text, dry_error = executor.run_tool("echo_tool", {"text": "hi"})
        self.assertFalse(dry_error)
        self.assertIn("dry_run", dry_text)
        self.assertEqual(len(base.calls), 0)

    def test_policy_tool_executor_prompt_callback(self) -> None:
        base = FakeExecutor()
        executor = PolicyToolExecutor(
            base_executor=base,
            permissions={"run_shell": "prompt"},
            approval_callback=lambda _name, _input: True,
            dry_run=False,
        )
        text, is_error = executor.run_tool("run_shell", {"command": "ls"})
        self.assertFalse(is_error)
        self.assertIn("run_shell", text)
        self.assertEqual(len(base.calls), 1)

    def test_logger_writes_jsonl(self) -> None:
        log_path = self.runtime_root / "chat.jsonl"
        logger = ChatLogger(log_file=str(log_path), session_id="test-session")
        logger.log("session_start", payload="ok")
        logger.next_turn()
        logger.log_tool_call("list_files", {"path": "."})
        text = log_path.read_text(encoding="utf-8")
        self.assertIn('"session_id": "test-session"', text)
        self.assertIn('"event": "thought"', text)
        self.assertIn('"event": "tool_call"', text)

    def test_request_queue_serializes_access(self) -> None:
        queue = RequestQueue()
        seq: list[int] = []

        def task(x: int) -> str:
            time.sleep(0.05)
            seq.append(x)
            return str(x)

        threads = [
            threading.Thread(target=lambda n=i: queue.run(lambda: task(n)))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(seq), [0, 1, 2, 3])

    def test_scheduler_heartbeat_and_job_callback(self) -> None:
        exec_ = FakeExecutor()
        events: list[dict] = []
        hb: list[dict] = []
        scheduler = JobScheduler(
            poll_seconds=5,
            tool_executor=exec_,
            on_job_run=lambda item: events.append(item),
            on_heartbeat=lambda item: hb.append(item),
        )
        scheduler._heartbeat()
        scheduler._loop = lambda: None  # type: ignore[method-assign]
        self.assertTrue(len(hb) >= 1)
        self.assertEqual(hb[0]["event"], "heartbeat")
