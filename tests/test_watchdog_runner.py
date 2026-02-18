from __future__ import annotations

from pathlib import Path
import os
import shutil
import unittest

import watchdog_runner


class TestWatchdogRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_watchdog"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_get_int_env_uses_default_on_invalid(self) -> None:
        key = "WATCHDOG_TEST_INT"
        old = os.environ.get(key)
        try:
            os.environ[key] = "not-a-number"
            self.assertEqual(watchdog_runner._get_int_env(key, default=7, minimum=1), 7)
            os.environ[key] = "0"
            self.assertEqual(watchdog_runner._get_int_env(key, default=7, minimum=3), 3)
            os.environ[key] = "9"
            self.assertEqual(watchdog_runner._get_int_env(key, default=7, minimum=3), 9)
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def test_sleep_with_stop_returns_true_when_stop_file_exists(self) -> None:
        case_dir = self.runtime_root / "sleep_true"
        case_dir.mkdir(parents=True, exist_ok=True)
        stop_file = case_dir / "stop"
        stop_file.write_text("1", encoding="utf-8")
        self.assertTrue(watchdog_runner._sleep_with_stop(1, stop_file))

    def test_sleep_with_stop_returns_false_when_no_stop_file(self) -> None:
        case_dir = self.runtime_root / "sleep_false"
        case_dir.mkdir(parents=True, exist_ok=True)
        stop_file = case_dir / "stop"
        self.assertFalse(watchdog_runner._sleep_with_stop(1, stop_file))

    def test_collect_guardian_report_detects_missing_dirs(self) -> None:
        case_dir = self.runtime_root / "guardian"
        case_dir.mkdir(parents=True, exist_ok=True)
        target = case_dir / "main.py"
        target.write_text("print('ok')\n", encoding="utf-8")
        stop_file = case_dir / "logs/stop"
        report = watchdog_runner._collect_guardian_report(
            workdir=case_dir,
            target_script=target,
            stop_file=stop_file,
            health_url="",
        )
        self.assertEqual(report["tier"], "level3_guardian")
        self.assertTrue(any(x.get("code") == "missing_runtime_dir" for x in report.get("issues", [])))
        self.assertTrue(any(x.get("type") == "create_dir" for x in report.get("recommended_actions", [])))

    def test_apply_safe_actions_creates_dir_and_updates_env(self) -> None:
        case_dir = self.runtime_root / "autofix"
        case_dir.mkdir(parents=True, exist_ok=True)
        actions = [
            {"type": "create_dir", "path": "logs"},
            {"type": "set_env", "key": "HEALTH_PORT", "value": "8099"},
        ]
        results = watchdog_runner._apply_safe_actions(case_dir, actions)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(bool(x.get("ok")) for x in results))
        self.assertTrue((case_dir / "logs").exists())
        env_text = (case_dir / ".env").read_text(encoding="utf-8")
        self.assertIn("HEALTH_PORT=8099", env_text)

    def test_emit_alert_writes_jsonl_record(self) -> None:
        case_dir = self.runtime_root / "alert"
        case_dir.mkdir(parents=True, exist_ok=True)
        alert_file = case_dir / "recovery_alerts.jsonl"
        watchdog_runner._emit_alert(
            alert_file=alert_file,
            event="emergency_recovery_failed",
            payload={"restart_count": 3},
        )
        text = alert_file.read_text(encoding="utf-8")
        self.assertIn("emergency_recovery_failed", text)
        self.assertIn("\"restart_count\": 3", text)
