from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import get_store


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_user_confirm",
    "description": "P1 scaffold for user confirmation request/response queue.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["request", "respond", "pending", "status"]},
            "startup_id": {"type": "string"},
            "collection_id": {"type": "string"},
            "confirmation_id": {"type": "string"},
            "channel": {"type": "string"},
            "message": {"type": "string"},
            "response": {"type": "string", "enum": ["confirm", "reject"]},
            "responder": {"type": "string"},
            "note": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["action"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action", "")).strip().lower()
    if not action:
        return {"success": False, "error": "action is required"}

    store = get_store(context)

    if action == "request":
        startup_id = str(input_data.get("startup_id", "")).strip().lower()
        if not startup_id:
            return {"success": False, "error": "startup_id is required"}
        confirmation_id = str(input_data.get("confirmation_id", "")).strip() or str(uuid4())
        collection_id = str(input_data.get("collection_id", "")).strip()
        channel = str(input_data.get("channel", "telegram")).strip() or "telegram"
        message = str(input_data.get("message", "수집 결과를 전송해도 되는지 확인 부탁드립니다.")).strip()
        store.create_user_confirmation(
            confirmation_id=confirmation_id,
            startup_id=startup_id,
            collection_id=collection_id,
            channel=channel,
            message=message,
            status="pending",
            response={},
        )
        row = store.get_user_confirmation(confirmation_id)
        return {"success": True, "action": action, "confirmation_id": confirmation_id, "confirmation": row}

    if action == "respond":
        confirmation_id = str(input_data.get("confirmation_id", "")).strip()
        response = str(input_data.get("response", "")).strip().lower()
        if not confirmation_id:
            return {"success": False, "error": "confirmation_id is required"}
        if response not in {"confirm", "reject"}:
            return {"success": False, "error": "response must be confirm|reject"}
        responder = str(input_data.get("responder", "")).strip()
        note = str(input_data.get("note", "")).strip()
        status = "confirmed" if response == "confirm" else "rejected"
        store.set_user_confirmation_response(
            confirmation_id=confirmation_id,
            status=status,
            responder=responder,
            response={"response": response, "note": note},
        )
        row = store.get_user_confirmation(confirmation_id)
        return {"success": True, "action": action, "confirmation": row}

    if action == "pending":
        startup_id = str(input_data.get("startup_id", "")).strip().lower() or None
        limit = int(input_data.get("limit", 100) or 100)
        rows = store.list_user_confirmations(startup_id=startup_id, status="pending", limit=limit)
        return {"success": True, "action": action, "count": len(rows), "confirmations": rows}

    if action == "status":
        confirmation_id = str(input_data.get("confirmation_id", "")).strip()
        if not confirmation_id:
            return {"success": False, "error": "confirmation_id is required"}
        row = store.get_user_confirmation(confirmation_id)
        if row is None:
            return {"success": False, "error": f"confirmation_id not found: {confirmation_id}"}
        return {"success": True, "action": action, "confirmation": row}

    return {"success": False, "error": f"unsupported action: {action}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_user_confirm cli")
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
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
