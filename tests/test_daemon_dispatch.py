from __future__ import annotations

import unittest
from unittest.mock import patch

from main import handle_daemon_service_command


class TestDaemonDispatch(unittest.TestCase):
    def test_no_flags_returns_false(self) -> None:
        handled = handle_daemon_service_command(install=False, uninstall=False, dry_run=True)
        self.assertFalse(handled)

    def test_install_darwin_calls_install_macos(self) -> None:
        with patch("platform.system", return_value="Darwin"), patch("install_daemon.install_macos") as install_macos:
            handled = handle_daemon_service_command(install=True, uninstall=False, dry_run=True)
        self.assertTrue(handled)
        install_macos.assert_called_once_with(dry_run=True)

    def test_uninstall_linux_calls_uninstall_linux(self) -> None:
        with patch("platform.system", return_value="Linux"), patch("install_daemon.uninstall_linux") as uninstall_linux:
            handled = handle_daemon_service_command(install=False, uninstall=True, dry_run=False)
        self.assertTrue(handled)
        uninstall_linux.assert_called_once_with(dry_run=False)

    def test_unsupported_platform_raises(self) -> None:
        with patch("platform.system", return_value="Windows"):
            with self.assertRaises(RuntimeError):
                handle_daemon_service_command(install=True, uninstall=False, dry_run=True)


if __name__ == "__main__":
    unittest.main()
