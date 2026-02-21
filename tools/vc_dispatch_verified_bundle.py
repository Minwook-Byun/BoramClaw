from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import get_store


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_dispatch_verified_bundle",
    "description": "P1 scaffold dispatch gate: require user confirmation before external delivery.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["preview", "dispatch"]},
            "startup_id": {"type": "string"},
            "collection_id": {"type": "string"},
            "confirmation_id": {"type": "string"},
            "recipient_emails": {
                "oneOf": [
                    {"type": "string", "description": "comma-separated emails"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
        },
        "required": ["action", "startup_id", "collection_id"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _as_recipients(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    else:
        items = []
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _resolve_confirmation(
    *,
    store: Any,
    startup_id: str,
    collection_id: str,
    confirmation_id: str,
) -> dict[str, Any] | None:
    if confirmation_id:
        row = store.get_user_confirmation(confirmation_id)
        if row and str(row.get("startup_id", "")) == startup_id and str(row.get("collection_id", "")) == collection_id:
            return row
        return None
    rows = store.list_user_confirmations(
        startup_id=startup_id,
        collection_id=collection_id,
        status="confirmed",
        limit=1,
    )
    if rows:
        return rows[0]
    return None


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action", "")).strip().lower()
    startup_id = str(input_data.get("startup_id", "")).strip().lower()
    collection_id = str(input_data.get("collection_id", "")).strip()
    if action not in {"preview", "dispatch"}:
        return {"success": False, "error": "action must be preview|dispatch"}
    if not startup_id:
        return {"success": False, "error": "startup_id is required"}
    if not collection_id:
        return {"success": False, "error": "collection_id is required"}

    recipients = _as_recipients(input_data.get("recipient_emails"))
    confirmation_id = str(input_data.get("confirmation_id", "")).strip()
    store = get_store(context)
    confirmation = _resolve_confirmation(
        store=store,
        startup_id=startup_id,
        collection_id=collection_id,
        confirmation_id=confirmation_id,
    )
    has_gate = bool(confirmation) and str(confirmation.get("status", "")) == "confirmed"
    if action == "preview":
        return {
            "success": True,
            "action": action,
            "startup_id": startup_id,
            "collection_id": collection_id,
            "recipient_count": len(recipients),
            "can_dispatch": has_gate and bool(recipients),
            "confirmation": confirmation,
        }

    if not has_gate:
        return {
            "success": False,
            "error": "confirmed user confirmation is required before dispatch",
            "startup_id": startup_id,
            "collection_id": collection_id,
        }
    if not recipients:
        return {"success": False, "error": "recipient_emails is required for dispatch"}

    return {
        "success": True,
        "action": action,
        "startup_id": startup_id,
        "collection_id": collection_id,
        "recipient_count": len(recipients),
        "dispatched": False,
        "notes": "P1 scaffold: 실제 메일 전송(외부 전송)은 안전 게이트만 검증하고 미구현 상태입니다.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_dispatch_verified_bundle cli")
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
