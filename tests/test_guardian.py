from __future__ import annotations

from pathlib import Path
import os
import shutil
import socket
import unittest

from config import BoramClawConfig
from guardian import run_guardian_preflight


def _make_config(case_root: Path, health_port: int = 8080) -> BoramClawConfig:
    tools_dir = case_root / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return BoramClawConfig(
        anthropic_api_key="sk-ant-test-key",
        claude_model="claude-sonnet-4-5-20250929",
        claude_max_tokens=1024,
        chat_log_file=str(case_root / "logs" / "chat.jsonl"),
        schedule_file=str(case_root / "schedules" / "jobs.json"),
        tool_workdir=str(case_root),
        tool_timeout_seconds=300,
        custom_tool_dir=str(tools_dir),
        strict_workdir_only=True,
        scheduler_enabled=True,
        scheduler_poll_seconds=30,
        agent_mode="interactive",
        claude_system_prompt="",
        chat_log_encryption_key="",
        force_tool_use=False,
        debug=False,
        dry_run=False,
        tool_permissions_json="",
        health_server_enabled=True,
        health_port=health_port,
        check_dependencies_on_start=True,
        session_log_split=False,
        log_base_dir=str(case_root / "logs" / "sessions"),
        keychain_service_name="BoramClaw",
        keychain_account_name="anthropic_api_key",
    )


class TestGuardian(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_guardian"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def setUp(self) -> None:
        self.case_root = self.runtime_root / self._testMethodName
        if self.case_root.exists():
            shutil.rmtree(self.case_root)
        self.case_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.case_root.exists():
            shutil.rmtree(self.case_root)

    def test_autofix_creates_runtime_dirs(self) -> None:
        cfg = _make_config(self.case_root)
        # remove runtime dirs so guardian can repair them
        shutil.rmtree(self.case_root / "tools")
        report = run_guardian_preflight(cfg, check_dependencies=False, auto_fix=True, auto_install_deps=False)
        self.assertGreaterEqual(report["issue_count"], 1)
        self.assertTrue((self.case_root / "logs").exists())
        self.assertTrue((self.case_root / "schedules").exists())
        self.assertTrue((self.case_root / "tasks").exists())
        self.assertTrue((self.case_root / "tools").exists())
        self.assertEqual(report["critical_count"], 0)

    def test_detects_health_port_conflict_and_reassigns(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        used_port = sock.getsockname()[1]
        try:
            cfg = _make_config(self.case_root, health_port=used_port)
            report = run_guardian_preflight(cfg, check_dependencies=False, auto_fix=True, auto_install_deps=False)
            codes = [item.get("code") for item in report.get("issues", []) if isinstance(item, dict)]
            self.assertIn("health_port_conflict", codes)
            self.assertNotEqual(cfg.health_port, used_port)
        finally:
            sock.close()

    def test_reports_missing_dependencies(self) -> None:
        cfg = _make_config(self.case_root)
        dep_script = self.case_root / "check_dependencies.py"
        dep_script.write_text(
            "REQUIRED_PACKAGES = ['fake-package']\n",
            encoding="utf-8",
        )
        report = run_guardian_preflight(cfg, check_dependencies=True, auto_fix=False, auto_install_deps=False)
        codes = [item.get("code") for item in report.get("issues", []) if isinstance(item, dict)]
        self.assertIn("missing_dependencies", codes)

    def test_config_validation_error_is_critical(self) -> None:
        cfg = _make_config(self.case_root)
        cfg.anthropic_api_key = "invalid-key"
        report = run_guardian_preflight(cfg, check_dependencies=False, auto_fix=False, auto_install_deps=False)
        self.assertGreaterEqual(report["critical_count"], 1)
        self.assertFalse(report["ok"])
