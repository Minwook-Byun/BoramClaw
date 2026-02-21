from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
    "name": "vc_monthly_collect",
    "description": "P1 scaffold monthly collection planner for integration connections.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "startup_id": {"type": "string"},
            "day_of_month": {"type": "integer", "minimum": 1, "maximum": 28},
            "mode": {"type": "string", "enum": ["preview", "run"]},
            "include_providers": {
                "oneOf": [
                    {"type": "string", "description": "comma-separated providers"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
        },
        "required": ["startup_id"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return []


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    startup_id = str(input_data.get("startup_id", "")).strip().lower()
    if not startup_id:
        return {"success": False, "error": "startup_id is required"}

    day_of_month = int(input_data.get("day_of_month", 20) or 20)
    day_of_month = max(1, min(day_of_month, 28))
    mode = str(input_data.get("mode", "preview")).strip().lower() or "preview"
    if mode not in {"preview", "run"}:
        return {"success": False, "error": "mode must be preview|run"}

    include_providers = _as_list(input_data.get("include_providers"))
    store = get_store(context)
    connections = store.list_integration_connections(startup_id=startup_id, status="connected", limit=200)
    if include_providers:
        include_set = set(include_providers)
        connections = [row for row in connections if str(row.get("provider", "")).lower() in include_set]

    now = datetime.now(timezone.utc)
    target_date = datetime(now.year, now.month, day_of_month, tzinfo=timezone.utc)
    if target_date < now:
        if now.month == 12:
            target_date = datetime(now.year + 1, 1, day_of_month, tzinfo=timezone.utc)
        else:
            target_date = datetime(now.year, now.month + 1, day_of_month, tzinfo=timezone.utc)

    plan = []
    for conn in connections:
        plan.append(
            {
                "connection_id": conn.get("connection_id"),
                "provider": conn.get("provider"),
                "startup_id": conn.get("startup_id"),
                "scheduled_at": target_date.isoformat(),
            }
        )

    return {
        "success": True,
        "startup_id": startup_id,
        "mode": mode,
        "day_of_month": day_of_month,
        "scheduled_at": target_date.isoformat(),
        "connection_count": len(plan),
        "plan": plan,
        "notes": "P1 scaffold: 실제 pull/검증/메일 발송 파이프라인 연결 전 단계입니다.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_monthly_collect cli")
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
