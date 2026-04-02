from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import get_registry, get_store


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_scope_policy",
    "description": "Manage VC consent scope policy and audit trail.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "set", "audit"]},
            "startup_id": {"type": "string"},
            "allow_prefixes": {
                "oneOf": [
                    {"type": "string", "description": "comma-separated prefixes"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "deny_patterns": {
                "oneOf": [
                    {"type": "string", "description": "comma-separated patterns"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "allowed_doc_types": {
                "oneOf": [
                    {"type": "string", "description": "comma-separated doc types"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "consent_reference": {"type": "string"},
            "retention_days": {"type": "integer"},
            "collection_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["allow", "reject"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
        },
        "required": ["action", "startup_id"],
    },
}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action", "")).strip().lower()
    startup_id = str(input_data.get("startup_id", "")).strip().lower()
    if not action:
        return {"success": False, "error": "action is required"}
    if not startup_id:
        return {"success": False, "error": "startup_id is required"}

    registry = get_registry(context)
    store = get_store(context)

    if action == "get":
        policy = registry.get_scope_policy(startup_id)
        return {"success": True, "action": action, "policy": policy}

    if action == "set":
        allow_prefixes = _as_list(input_data.get("allow_prefixes"))
        deny_patterns = _as_list(input_data.get("deny_patterns"))
        allowed_doc_types = _as_list(input_data.get("allowed_doc_types"))
        consent_reference = input_data.get("consent_reference")
        retention_days_raw = input_data.get("retention_days")
        retention_days = int(retention_days_raw) if retention_days_raw is not None else None

        tenant = registry.update_scope_policy(
            startup_id=startup_id,
            allow_prefixes=(allow_prefixes if allow_prefixes else None),
            deny_patterns=(deny_patterns if deny_patterns else None),
            allowed_doc_types=(allowed_doc_types if allowed_doc_types else None),
            consent_reference=(str(consent_reference) if consent_reference is not None else None),
            retention_days=retention_days,
        )
        policy = registry.get_scope_policy(startup_id)
        return {"success": True, "action": action, "tenant": tenant, "policy": policy}

    if action == "audit":
        collection_id = str(input_data.get("collection_id", "")).strip() or None
        decision = str(input_data.get("decision", "")).strip().lower() or None
        if decision not in {None, "allow", "reject"}:
            return {"success": False, "error": "decision must be allow/reject"}
        limit = int(input_data.get("limit", 100) or 100)
        rows = store.list_scope_audits(
            startup_id=startup_id,
            collection_id=collection_id,
            decision=decision,
            limit=limit,
        )
        return {"success": True, "action": action, "count": len(rows), "audits": rows}

    return {"success": False, "error": f"unsupported action: {action}"}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_scope_policy cli")
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
