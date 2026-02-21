from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import unittest
from unittest.mock import patch

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
        windows_cmd = install_daemon.build_windows_command(root=root, python_path=py)
        self.assertIn("AGENT_MODE=daemon", windows_cmd)
        self.assertIn("watchdog_runner.py", windows_cmd)
        gw_cmd = install_daemon.build_windows_command(
            root=root,
            python_path=py,
            mode="gateway",
            gateway_config="config/vc_gateway.json",
        )
        self.assertIn("vc_gateway_agent.py", gw_cmd)
        self.assertIn("--config", gw_cmd)
        self.assertIn("/tmp/boram/config/vc_gateway.json", gw_cmd)

    def test_resolve_python_bin_uses_env_override_and_checks_min_version(self) -> None:
        with patch.dict("os.environ", {"BORAMCLAW_PYTHON_BIN": "/custom/python3", "BORAMCLAW_MIN_PYTHON": "3.10"}):
            with patch("install_daemon.subprocess.run") as run_mock:
                run_mock.return_value = subprocess.CompletedProcess(
                    args=["/custom/python3"],
                    returncode=0,
                    stdout="3.11\n",
                    stderr="",
                )
                resolved = install_daemon.resolve_python_bin()
        self.assertEqual(resolved, "/custom/python3")

    def test_resolve_python_bin_raises_when_version_too_low(self) -> None:
        with self.assertRaises(RuntimeError):
            install_daemon.resolve_python_bin(python_bin=sys.executable, min_python="99.0")

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

    def test_install_windows_missing_schtasks_raises_friendly_error(self) -> None:
        with patch("install_daemon.subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(RuntimeError) as exc:
                install_daemon.install_windows(dry_run=False, mode="gateway", gateway_config="config/vc_gateway.json")
        self.assertIn("schtasks", str(exc.exception))

    def test_install_windows_called_process_error_contains_hint(self) -> None:
        side_effect = [
            subprocess.CompletedProcess(args=["schtasks"], returncode=0, stdout="", stderr=""),
            subprocess.CalledProcessError(
                1,
                ["schtasks", "/Create"],
                output="",
                stderr="Access is denied.",
            ),
        ]
        with patch("install_daemon.subprocess.run", side_effect=side_effect):
            with self.assertRaises(RuntimeError) as exc:
                install_daemon.install_windows(dry_run=False, mode="agent")
        self.assertIn("exit=1", str(exc.exception))
        self.assertIn("권한 부족", str(exc.exception))

    def test_uninstall_windows_not_found_is_non_fatal(self) -> None:
        result = subprocess.CompletedProcess(
            args=["schtasks", "/Delete"],
            returncode=1,
            stdout="ERROR: The system cannot find the file specified.",
            stderr="",
        )
        with patch("install_daemon.subprocess.run", return_value=result):
            install_daemon.uninstall_windows(dry_run=False, mode="agent")

    def test_uninstall_windows_other_error_raises(self) -> None:
        result = subprocess.CompletedProcess(
            args=["schtasks", "/Delete"],
            returncode=1,
            stdout="",
            stderr="Access is denied.",
        )
        with patch("install_daemon.subprocess.run", return_value=result):
            with self.assertRaises(RuntimeError) as exc:
                install_daemon.uninstall_windows(dry_run=False, mode="agent")
        self.assertIn("uninstall", str(exc.exception))
