"""macOS 알림 유틸 테스트."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.macos_notify import notify


class TestNotify(unittest.TestCase):
    """notify() 함수 테스트."""

    @patch("utils.macos_notify.sys")
    def test_non_darwin_returns_false(self, mock_sys):
        mock_sys.platform = "linux"
        result = notify("Test", "Hello")
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_success_returns_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = notify("BoramClaw", "테스트 알림")
        self.assertTrue(result)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_osascript_called_with_correct_args(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        notify("Title", "Body", sound="Glass", subtitle="Sub")
        call_args = mock_run.call_args
        script = call_args[0][0]  # first positional arg is the command list
        self.assertEqual(script[0], "osascript")
        self.assertEqual(script[1], "-e")
        self.assertIn("Title", script[2])
        self.assertIn("Body", script[2])
        self.assertIn("Glass", script[2])
        self.assertIn("Sub", script[2])

    @patch("subprocess.run")
    def test_no_sound(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        notify("Title", "Body", sound="")
        script = mock_run.call_args[0][0][2]
        self.assertNotIn("sound name", script)

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_osascript_not_found(self, mock_run):
        result = notify("Title", "Body")
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_special_chars_escaped(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        notify('He said "hello"', 'Path: C:\\Users')
        script = mock_run.call_args[0][0][2]
        # 따옴표와 백슬래시가 이스케이프됐는지 확인
        self.assertNotIn('""', script.replace('\\"', ''))


if __name__ == "__main__":
    unittest.main()
