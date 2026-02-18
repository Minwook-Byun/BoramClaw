from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
import urllib.parse
import urllib.request

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "telegram_send_message",
    "description": "Send a message to Telegram chat using bot token (env or input).",
    "version": "1.0.0",
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "chat_id": {"type": "string"},
            "bot_token": {"type": "string"},
        },
        "required": ["text"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _send_message(bot_token: str, chat_id: str, text: str) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
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
    if not bool(parsed.get("ok")):
        raise RuntimeError(f"telegram api error: {parsed}")
    return parsed


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    text = str(input_data.get("text", "")).strip()
    if not text:
        return {"ok": False, "error": "text is required"}
    bot_token = str(input_data.get("bot_token", "")).strip() or (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token:
        return {"ok": False, "error": "bot_token is required (input.bot_token or TELEGRAM_BOT_TOKEN env)"}
    chat_id = str(input_data.get("chat_id", "")).strip() or (os.getenv("TELEGRAM_ALLOWED_CHAT_ID") or "").strip()
    if not chat_id:
        return {"ok": False, "error": "chat_id is required (input.chat_id or TELEGRAM_ALLOWED_CHAT_ID env)"}

    payload = _send_message(bot_token=bot_token, chat_id=chat_id, text=text)
    msg = payload.get("result", {})
    if not isinstance(msg, dict):
        msg = {}
    return {
        "ok": True,
        "chat_id": chat_id,
        "message_id": msg.get("message_id"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="telegram_send_message cli")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()
    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0
        input_data = _load_json_object(args.tool_input_json)
        context = _load_json_object(args.tool_context_json)
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

