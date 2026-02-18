from __future__ import annotations

import unittest

from gateway import ClaudeChat


class _FakeUsageChat(ClaudeChat):
    def __init__(self) -> None:
        super().__init__(api_key="test", model="test-model", max_tokens=128, system_prompt="")
        self._responses: list[dict] = []

    def queue_response(self, payload: dict) -> None:
        self._responses.append(payload)

    def _request(self, messages, tools=None):  # type: ignore[override]
        if not self._responses:
            raise RuntimeError("no fake response queued")
        payload = self._responses.pop(0)
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self._pending_usage["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            self._pending_usage["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            self._pending_usage["requests"] += 1
            self._total_usage["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            self._total_usage["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            self._total_usage["requests"] += 1
        return payload


class TestGatewayUsage(unittest.TestCase):
    def test_usage_snapshot_without_tools(self) -> None:
        chat = _FakeUsageChat()
        chat.queue_response(
            {
                "content": [{"type": "text", "text": "안녕하세요"}],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            }
        )
        answer = chat.ask("안녕")
        self.assertEqual(answer, "안녕하세요")
        usage = chat.consume_pending_usage()
        self.assertEqual(usage["input_tokens"], 11)
        self.assertEqual(usage["output_tokens"], 7)
        self.assertEqual(usage["requests"], 1)
        total = chat.get_total_usage()
        self.assertEqual(total["requests"], 1)

    def test_usage_snapshot_with_tool_loop(self) -> None:
        chat = _FakeUsageChat()
        chat.queue_response(
            {
                "content": [{"type": "tool_use", "id": "tool-1", "name": "echo_tool", "input": {"text": "x"}}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        )
        chat.queue_response(
            {
                "content": [{"type": "text", "text": "도구 실행 완료"}],
                "usage": {"input_tokens": 8, "output_tokens": 3},
            }
        )

        def runner(name: str, input_data: dict):
            self.assertEqual(name, "echo_tool")
            self.assertEqual(input_data.get("text"), "x")
            return '{"ok":true}', False

        answer = chat.ask(
            "도구 실행해",
            tools=[{"name": "echo_tool", "description": "echo", "input_schema": {"type": "object"}}],
            tool_runner=runner,
            on_tool_event=None,
        )
        self.assertEqual(answer, "도구 실행 완료")
        usage = chat.consume_pending_usage()
        self.assertEqual(usage["input_tokens"], 18)
        self.assertEqual(usage["output_tokens"], 8)
        self.assertEqual(usage["requests"], 2)

