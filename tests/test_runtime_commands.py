from __future__ import annotations

import unittest

from runtime_commands import (
    format_permissions_map,
    format_user_output,
    parse_arxiv_quick_request,
    parse_deep_weekly_quick_request,
    parse_feedback_command,
    parse_memory_command,
    parse_reflexion_command,
    parse_schedule_arxiv_command,
    parse_set_permission_command,
    parse_tool_command,
)


class TestRuntimeCommands(unittest.TestCase):
    def test_parse_tool_command(self) -> None:
        self.assertEqual(parse_tool_command("/tool list_files"), ("list_files", {}))
        name, payload = parse_tool_command('/tool echo_tool {"text":"hello"}')  # type: ignore[misc]
        self.assertEqual(name, "echo_tool")
        self.assertEqual(payload["text"], "hello")

    def test_parse_permission_and_memory(self) -> None:
        self.assertEqual(parse_set_permission_command("/set-permission run_shell deny"), ("run_shell", "deny"))
        self.assertEqual(parse_memory_command("/memory latest 3"), {"action": "latest", "count": 3})
        self.assertEqual(parse_reflexion_command("/reflexion status"), {"action": "status"})

    def test_parse_feedback_command(self) -> None:
        self.assertEqual(parse_feedback_command("/feedback 루프 개선해"), "루프 개선해")
        with self.assertRaises(ValueError):
            parse_feedback_command("/feedback")

    def test_parse_arxiv_quick_request(self) -> None:
        payload = parse_arxiv_quick_request("아카이브에서 DeepSeek 관련 논문 2개 요약해줘")
        assert payload is not None
        self.assertEqual(payload["max_papers"], 2)
        self.assertIn("deepseek", payload.get("keywords", []))

    def test_parse_deep_weekly_quick_request(self) -> None:
        payload = parse_deep_weekly_quick_request("이번 주 깊이 있는 회고 작성해줘")
        assert payload is not None
        self.assertEqual(payload["days_back"], 7)

        payload_14 = parse_deep_weekly_quick_request("지난 14일 깊은 회고 정리해줘")
        assert payload_14 is not None
        self.assertEqual(payload_14["days_back"], 14)

        payload_2w = parse_deep_weekly_quick_request("deep_weekly_retrospective 2주 실행해줘")
        assert payload_2w is not None
        self.assertEqual(payload_2w["days_back"], 14)

        self.assertIsNone(parse_deep_weekly_quick_request("이번 주 회고 알려줘"))

    def test_parse_schedule_arxiv_command(self) -> None:
        cmd = parse_schedule_arxiv_command("/schedule-arxiv 08:00 deepseek llm")
        assert cmd is not None
        self.assertEqual(cmd["time"], "08:00")
        self.assertIn("deepseek", cmd["keywords"])

    def test_format_user_output_and_permissions(self) -> None:
        self.assertEqual(format_user_output('{"summary":"ok"}'), "ok")
        self.assertIn("run_shell", format_permissions_map({"run_shell": "prompt"}))


if __name__ == "__main__":
    unittest.main()
