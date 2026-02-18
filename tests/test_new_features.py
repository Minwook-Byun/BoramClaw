from __future__ import annotations

import json
from pathlib import Path
import platform
import tempfile
import unittest

import check_dependencies
import keychain_helper
import watchdog_runner


class TestNewFeatures(unittest.TestCase):
    def test_check_dependencies_constants(self) -> None:
        self.assertIn("anthropic", check_dependencies.REQUIRED_PACKAGES)
        self.assertIn("feedparser", check_dependencies.REQUIRED_PACKAGES)

    def test_keychain_helper_non_macos(self) -> None:
        if platform.system() == "Darwin":
            self.skipTest("macOS keychain behavior depends on local keychain state")
        with self.assertRaises(NotImplementedError):
            keychain_helper.load_api_key("BoramClaw", "anthropic_api_key")

    def test_watchdog_health_check_false_on_bad_url(self) -> None:
        self.assertFalse(watchdog_runner._check_health("http://127.0.0.1:65534/health", timeout_seconds=1))

    def test_watchdog_append_metric(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(Path.cwd() / "logs")) as td:
            path = Path(td) / "metrics.jsonl"
            watchdog_runner._append_metric(path, {"event": "unit_test", "ok": True})
            rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event"], "unit_test")

