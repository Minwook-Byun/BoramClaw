from __future__ import annotations

import argparse
import json
import sys
import subprocess
from typing import Any

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "run_tool",
    "description": "Execute a custom tool by name with input parameters.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_name": {"type": "string", "description": "Name of the tool to execute"},
            "tool_input": {"type": "object", "description": "Input parameters for the tool"},
        },
        "required": ["tool_name", "tool_input"],
    },
}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    
    if not tool_name:
        return {"ok": False, "error": "tool_name is required"}
    
    # Construct the tool path
    tool_path = f"tools/{tool_name}.py"
    
    # Prepare the command
    cmd = [
        sys.executable,
        tool_path,
        "--tool-input-json", json.dumps(tool_input, ensure_ascii=False),
        "--tool-context-json", json.dumps(context, ensure_ascii=False)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            output = json.loads(result.stdout)
            return {
                "ok": True,
                "tool_name": tool_name,
                "result": output
            }
        else:
            return {
                "ok": False,
                "tool_name": tool_name,
                "error": result.stderr or result.stdout
            }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Tool execution timed out"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="run_tool cli")
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
