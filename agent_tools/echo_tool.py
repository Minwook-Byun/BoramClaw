from typing import Any

TOOL_SPEC = {
    "name": "echo_tool",
    "description": "Echo text and optionally transform case.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "mode": {"type": "string", "enum": ["raw", "upper", "lower"]},
        },
        "required": ["text"],
    },
}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    text = str(input_data.get("text", ""))
    mode = str(input_data.get("mode", "raw"))

    if mode == "upper":
        value = text.upper()
    elif mode == "lower":
        value = text.lower()
    else:
        value = text

    return {
        "value": value,
        "workdir": context.get("workdir", ""),
    }
