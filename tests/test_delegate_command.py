from __future__ import annotations

import unittest

from main import parse_delegate_command


class TestDelegateCommand(unittest.TestCase):
    def test_parse_delegate_command_ok(self) -> None:
        self.assertEqual(parse_delegate_command("/delegate 아카이브 논문 요약"), "아카이브 논문 요약")

    def test_parse_delegate_command_none(self) -> None:
        self.assertIsNone(parse_delegate_command("안녕"))

    def test_parse_delegate_command_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_delegate_command("/delegate")


if __name__ == "__main__":
    unittest.main()
