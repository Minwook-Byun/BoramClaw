from __future__ import annotations

import unittest

from main import parse_tool_only_mode_command


class TestToolOnlyModeCommand(unittest.TestCase):
    def test_enable_commands(self) -> None:
        self.assertTrue(parse_tool_only_mode_command("/tool-only on"))
        self.assertTrue(parse_tool_only_mode_command("도구만 사용"))
        self.assertTrue(parse_tool_only_mode_command("앞으로 도구만 사용해서 답하거라"))

    def test_disable_commands(self) -> None:
        self.assertFalse(parse_tool_only_mode_command("/tool-only off"))
        self.assertFalse(parse_tool_only_mode_command("도구만 해제"))
        self.assertFalse(parse_tool_only_mode_command("disable tool-only now"))

    def test_non_command_returns_none(self) -> None:
        self.assertIsNone(parse_tool_only_mode_command("저게 딥시크 관련 논문이야?"))
        self.assertIsNone(parse_tool_only_mode_command("오늘 날씨 알려줘"))

