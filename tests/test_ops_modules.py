from __future__ import annotations

import json
from pathlib import Path
import urllib.request
import unittest

import install_daemon
from health_server import start_health_server


class TestOpsModules(unittest.TestCase):
    def test_install_daemon_builders(self) -> None:
        root = Path("/tmp/boram")
        py = "/usr/bin/python3"
        plist = install_daemon.build_macos_plist(root=root, python_path=py)
        self.assertIn("com.boramclaw.agent", plist)
        self.assertIn("watchdog_runner.py", plist)
        service = install_daemon.build_linux_service(root=root, python_path=py)
        self.assertIn("Description=BoramClaw Autonomous Agent", service)
        self.assertIn("ExecStart=/usr/bin/python3 /tmp/boram/watchdog_runner.py", service)

    def test_health_server_endpoint(self) -> None:
        server = start_health_server(port=0, agent_mode="daemon")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/health", timeout=3) as resp:
                self.assertEqual(resp.status, 200)
                payload = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["agent_mode"], "daemon")
        finally:
            server.stop()
