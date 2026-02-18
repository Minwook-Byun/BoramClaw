from __future__ import annotations

from pathlib import Path
import unittest


class TestMainSlim(unittest.TestCase):
    def test_main_no_longer_contains_runtime_parser_defs(self) -> None:
        text = (Path.cwd() / "main.py").read_text(encoding="utf-8")
        forbidden_defs = [
            "def parse_tool_command(",
            "def parse_memory_command(",
            "def parse_reflexion_command(",
            "def parse_feedback_command(",
            "def parse_delegate_command(",
            "def format_user_output(",
        ]
        for marker in forbidden_defs:
            self.assertNotIn(marker, text)

    def test_runtime_commands_has_parser_defs(self) -> None:
        text = (Path.cwd() / "runtime_commands.py").read_text(encoding="utf-8")
        required_defs = [
            "def parse_tool_command(",
            "def parse_memory_command(",
            "def parse_reflexion_command(",
            "def parse_feedback_command(",
            "def parse_delegate_command(",
            "def format_user_output(",
        ]
        for marker in required_defs:
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
