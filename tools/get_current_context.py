#!/usr/bin/env python3
"""
get_current_context.py
현재 작업 맥락 조회 툴

Context Engine을 사용하여 현재 작업 중인 내용을 자동으로 파악합니다.
"""
import sys
import json
import argparse
from pathlib import Path

# Context Engine import
sys.path.insert(0, str(Path(__file__).parent.parent))
from context_engine import ContextEngine, format_context_display

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "get_current_context",
    "description": "현재 작업 맥락을 조회합니다. 최근 활동(Git, Shell, Browser)을 분석하여 현재 무엇을 하고 있는지 자동으로 파악합니다.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "lookback_minutes": {
                "type": "integer",
                "description": "최근 몇 분간의 활동을 조회할지 (기본값: 30분)",
                "default": 30,
            },
            "repo_path": {
                "type": "string",
                "description": "Git 저장소 경로 (기본값: 현재 디렉토리)",
                "default": ".",
            },
            "include_screen": {
                "type": "boolean",
                "description": "Screen 활동 포함 여부 (기본값: false)",
                "default": False,
            },
            "screen_keyword": {
                "type": "string",
                "description": "Screen 검색 키워드 (include_screen=true일 때만)",
            },
            "format": {
                "type": "string",
                "enum": ["text", "json"],
                "description": "출력 포맷 (기본값: text)",
                "default": "text",
            },
        },
        "required": [],
    },
}


def run(input_data: dict, context: dict) -> dict:
    """
    현재 작업 맥락 조회

    Args:
        input_data: {
            "lookback_minutes": 30,
            "repo_path": ".",
            "include_screen": false,
            "screen_keyword": "",
            "format": "text"
        }
        context: 실행 컨텍스트

    Returns:
        {"ok": true, "context": {...}, "formatted": "..."}
    """
    lookback_minutes = input_data.get("lookback_minutes", 30)
    repo_path = input_data.get("repo_path", ".")
    include_screen = input_data.get("include_screen", False)
    screen_keyword = input_data.get("screen_keyword")
    output_format = input_data.get("format", "text")

    try:
        engine = ContextEngine(lookback_minutes=lookback_minutes)
        current_context = engine.get_current_context(
            repo_path=repo_path,
            include_screen=include_screen,
            screen_keyword=screen_keyword,
        )

        if output_format == "json":
            return {
                "ok": True,
                "context": current_context,
            }
        else:
            formatted = format_context_display(current_context)
            return {
                "ok": True,
                "context": current_context,
                "formatted": formatted,
            }

    except Exception as e:
        return {
            "ok": False,
            "error": f"컨텍스트 조회 실패: {str(e)}",
        }


def main():
    parser = argparse.ArgumentParser(description=TOOL_SPEC["description"])
    parser.add_argument(
        "--tool-spec-json",
        action="store_true",
        help="Print tool specification as JSON",
    )
    parser.add_argument(
        "--tool-input-json",
        type=str,
        help="Tool input as JSON string",
    )
    parser.add_argument(
        "--tool-context-json",
        type=str,
        default="{}",
        help="Tool context as JSON string",
    )

    args = parser.parse_args()

    if args.tool_spec_json:
        print(json.dumps(TOOL_SPEC, ensure_ascii=False, indent=2))
        return

    if not args.tool_input_json:
        # 기본값으로 실행
        input_data = {}
    else:
        try:
            input_data = json.loads(args.tool_input_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {str(e)}"}, ensure_ascii=False))
            sys.exit(1)

    try:
        tool_context = json.loads(args.tool_context_json)
        result = run(input_data, tool_context)

        # text 포맷일 때는 formatted 출력
        if result.get("ok") and result.get("formatted"):
            print(result["formatted"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
