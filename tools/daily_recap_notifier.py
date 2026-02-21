#!/usr/bin/env python3
"""
daily_recap_notifier.py
매일 workday_recap을 실행하고 결과를 파일로 저장 + macOS 알림 전송

schedule_daily_tool로 등록하여 매일 21:00에 자동 실행하도록 설계됨
"""
import sys
import json
import argparse
import os
from pathlib import Path
from datetime import datetime

# 다른 툴들 import
sys.path.insert(0, str(Path(__file__).parent))
from workday_recap import run as workday_recap_run

# utils import
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.macos_notify import notify as macos_notify

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "daily_recap_notifier",
    "description": "매일 개발 활동 리포트를 생성하고 파일로 저장한 뒤 macOS 알림을 전송합니다.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "output_dir": {
                "type": "string",
                "description": "리포트 저장 디렉토리 (기본값: logs/summaries/daily)",
            },
            "notify": {
                "type": "boolean",
                "description": "macOS 알림 전송 여부 (기본값: true)",
            },
        },
        "required": [],
    },
}


def run(input_data: dict, context: dict) -> dict:
    """
    Daily recap 생성 + 파일 저장 + 알림

    Args:
        input_data: {"output_dir": "...", "notify": true}
        context: 실행 컨텍스트

    Returns:
        실행 결과 dict
    """
    output_dir = input_data.get("output_dir", "logs/summaries/daily")
    should_notify = input_data.get("notify", True)

    # 1. workday_recap 실행
    try:
        recap_result = workday_recap_run({"mode": "daily"}, context)
    except Exception as e:
        error_msg = f"workday_recap 실행 실패: {str(e)}"
        if should_notify:
            macos_notify("일일 리포트 실패", error_msg, sound="Basso")
        return {
            "ok": False,
            "error": error_msg,
        }

    if recap_result.get("status") != "success":
        error_msg = "workday_recap 실행 결과가 성공이 아닙니다."
        if should_notify:
            macos_notify("일일 리포트 실패", error_msg, sound="Basso")
        return {
            "ok": False,
            "error": error_msg,
        }

    report = recap_result.get("report", {})
    summary = report.get("summary", "")

    # 2. 파일로 저장
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{today_str}.json"
    filepath = Path(output_dir) / filename

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_msg = f"파일 저장 실패: {str(e)}"
        if should_notify:
            macos_notify("일일 리포트 저장 실패", error_msg, sound="Basso")
        return {
            "ok": False,
            "error": error_msg,
        }

    # 3. macOS 알림
    if should_notify:
        try:
            macos_notify(
                "오늘 개발 활동 리포트 생성 완료",
                summary,
                sound="Glass",
                subtitle=f"저장: {filepath}",
            )
        except Exception as e:
            # 알림 실패는 전체 실패로 처리하지 않음
            pass

    return {
        "ok": True,
        "summary": summary,
        "file_path": str(filepath),
        "sections": list(report.get("sections", {}).keys()),
        "errors": report.get("errors", []),
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
        context = json.loads(args.tool_context_json)
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
