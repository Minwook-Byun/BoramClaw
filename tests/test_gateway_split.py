from __future__ import annotations

from pathlib import Path
import unittest

import gateway


class TestGatewaySplit(unittest.TestCase):
    def test_main_does_not_define_claude_chat(self) -> None:
        text = (Path.cwd() / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("class ClaudeChat", text)

    def test_gateway_exposes_claude_chat(self) -> None:
        self.assertTrue(hasattr(gateway, "ClaudeChat"))
        self.assertTrue(callable(getattr(gateway, "ClaudeChat")))

