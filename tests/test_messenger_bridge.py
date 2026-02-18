from __future__ import annotations

import unittest

from messenger_bridge import TelegramBridge, _chunk_text


class TestMessengerBridge(unittest.TestCase):
    def test_chunk_text(self) -> None:
        chunks = _chunk_text("a" * 9000, limit=3900)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))

    def test_handle_update_allowed_chat(self) -> None:
        sent: list[tuple[int, str]] = []

        bridge = TelegramBridge(
            bot_token="dummy-token",
            ask_callback=lambda text: f"답:{text}",
            allowed_chat_id=123,
            poll_interval_seconds=1.0,
        )
        bridge._send_message = lambda chat_id, text: sent.append((chat_id, text))  # type: ignore[method-assign]

        bridge._handle_update(
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": 123},
                    "text": "안녕",
                },
            }
        )
        self.assertEqual(sent, [(123, "답:안녕")])

    def test_handle_update_rejects_other_chat(self) -> None:
        sent: list[tuple[int, str]] = []

        bridge = TelegramBridge(
            bot_token="dummy-token",
            ask_callback=lambda text: f"답:{text}",
            allowed_chat_id=123,
            poll_interval_seconds=1.0,
        )
        bridge._send_message = lambda chat_id, text: sent.append((chat_id, text))  # type: ignore[method-assign]

        bridge._handle_update(
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": 999},
                    "text": "안녕",
                },
            }
        )
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()

