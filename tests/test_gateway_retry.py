from __future__ import annotations

from unittest.mock import patch
import unittest

from gateway import ClaudeChat


class _RetryChat(ClaudeChat):
    def __init__(self, steps: list[object]) -> None:
        super().__init__(api_key="test", model="test-model", max_tokens=64, system_prompt="")
        self.steps = list(steps)
        self.calls = 0

    def _perform_http_request(self, body: bytes) -> tuple[int, bytes]:  # type: ignore[override]
        if self.calls >= len(self.steps):
            raise RuntimeError("no more steps")
        step = self.steps[self.calls]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        status, payload = step  # type: ignore[misc]
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return int(status), payload


class TestGatewayRetry(unittest.TestCase):
    def test_retry_on_5xx_then_success(self) -> None:
        chat = _RetryChat(
            [
                (500, '{"error":{"message":"temporary"}}'),
                (200, '{"content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":1,"output_tokens":1}}'),
            ]
        )
        with patch("gateway.time.sleep", return_value=None):
            answer = chat.ask("안녕")
        self.assertEqual(answer, "ok")
        self.assertEqual(chat.calls, 2)

    def test_retry_on_connection_error_then_fail(self) -> None:
        chat = _RetryChat([OSError("boom"), OSError("boom"), OSError("boom")])
        with patch("gateway.time.sleep", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                chat.ask("안녕")
        self.assertIn("API 연결 오류", str(ctx.exception))
        self.assertEqual(chat.calls, 3)

