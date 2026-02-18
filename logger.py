from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
from typing import Any


class ChatLogger:
    def __init__(self, log_file: str, session_id: str | None = None) -> None:
        self.log_path = Path(log_file)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.turn = 0
        self.lock = threading.Lock()
        self._logger = logging.getLogger(f"boramclaw.chat.{self.session_id}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._logger.handlers.clear()
        handler = RotatingFileHandler(
            self.log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

    def log(self, event: str, payload: str, **extra: object) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "turn": self.turn,
            "event": event,
            "payload": payload,
        }
        if extra:
            record.update(extra)
        line = json.dumps(record, ensure_ascii=False)
        with self.lock:
            self._logger.info(line)

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.log(event_type, payload=json.dumps(payload, ensure_ascii=False))

    def log_tool_call(self, tool_name: str, input_data: dict[str, Any]) -> None:
        self.log_event(
            "thought",
            {
                "reasoning": f"I need to call {tool_name} to proceed",
                "tool": tool_name,
            },
        )
        self.log_event(
            "tool_call",
            {
                "tool": tool_name,
                "input": input_data,
            },
        )

    def next_turn(self) -> None:
        self.turn += 1
