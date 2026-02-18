#!/usr/bin/env python3
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable


class TelegramBridge:
    def __init__(
        self,
        *,
        bot_token: str,
        ask_callback: Callable[[str], str],
        allowed_chat_id: int | None = None,
        poll_interval_seconds: float = 1.0,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.bot_token = bot_token.strip()
        if not self.bot_token:
            raise ValueError("bot_token is required")
        self.ask_callback = ask_callback
        self.allowed_chat_id = allowed_chat_id
        self.poll_interval_seconds = max(0.2, float(poll_interval_seconds))
        self.on_log = on_log
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: int | None = None

    def _log(self, message: str) -> None:
        if self.on_log is not None:
            self.on_log(message)

    def _api_json(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        body = urllib.parse.urlencode({k: str(v) for k, v in params.items()}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("telegram api invalid payload")
        ok = bool(parsed.get("ok"))
        if not ok:
            raise RuntimeError(f"telegram api error: {parsed}")
        return parsed

    def _send_message(self, chat_id: int, text: str) -> None:
        chunks = _chunk_text(text, limit=3900)
        for chunk in chunks:
            self._api_json(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                },
            )

    def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id = int(chat.get("id", 0) or 0)
        if self.allowed_chat_id is not None and chat_id != self.allowed_chat_id:
            self._log(f"telegram chat id not allowed: {chat_id}")
            return
        text = str(message.get("text", "")).strip()
        if not text:
            return
        try:
            answer = str(self.ask_callback(text))
        except Exception as exc:
            answer = f"요청 처리 중 오류가 발생했습니다: {exc}"
        self._send_message(chat_id, answer)

    def _poll_once(self) -> None:
        params: dict[str, Any] = {"timeout": 20}
        if self._offset is not None:
            params["offset"] = self._offset
        payload = self._api_json("getUpdates", params)
        updates = payload.get("result", [])
        if not isinstance(updates, list):
            return
        for item in updates:
            if not isinstance(item, dict):
                continue
            update_id = int(item.get("update_id", 0) or 0)
            if update_id > 0:
                self._offset = update_id + 1
            self._handle_update(item)

    def _loop(self) -> None:
        self._log("telegram bridge loop started")
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                self._log(f"telegram bridge error: {exc}")
                time.sleep(max(self.poll_interval_seconds, 1.0))
            else:
                time.sleep(self.poll_interval_seconds)
        self._log("telegram bridge loop stopped")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="boramclaw-telegram")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)


def _chunk_text(text: str, limit: int = 3900) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return [""]
    chunks: list[str] = []
    remaining = cleaned
    while len(remaining) > limit:
        idx = remaining.rfind("\n", 0, limit)
        if idx <= 0:
            idx = limit
        chunks.append(remaining[:idx].strip())
        remaining = remaining[idx:].strip()
    chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]

