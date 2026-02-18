from __future__ import annotations

import unittest

from main import format_permissions_map, parse_set_permission_command


class TestPermissionCommands(unittest.TestCase):
    def test_parse_set_permission_command_ok(self) -> None:
        parsed = parse_set_permission_command("/set-permission run_shell deny")
        self.assertEqual(parsed, ("run_shell", "deny"))

    def test_parse_set_permission_command_invalid_mode(self) -> None:
        with self.assertRaises(ValueError):
            parse_set_permission_command("/set-permission run_shell block")

    def test_parse_set_permission_command_non_command(self) -> None:
        self.assertIsNone(parse_set_permission_command("안녕"))

    def test_format_permissions_map(self) -> None:
        text = format_permissions_map({"run_shell": "prompt", "write_file": "allow"})
        self.assertIn("run_shell: prompt", text)
        self.assertIn("write_file: allow", text)

