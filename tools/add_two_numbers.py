from __future__ import annotations

import argparse
import json
import sys
from typing import Any

__version__ = "1.1.0"

TOOL_SPEC = {
    "name": "add_two_numbers",
    "description": "Add two numbers and return the sum.",
    "version": "1.1.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
    },
}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    a = float(input_data.get("a", 0))
    b = float(input_data.get("b", 0))
    total = a + b
    return {
        "a": a,
        "b": b,
        "sum": total,
        "workdir": context.get("workdir", ""),
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="add_two_numbers cli")
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
