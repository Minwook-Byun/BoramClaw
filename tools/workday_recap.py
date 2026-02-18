#!/usr/bin/env python3
"""
workday_recap.py
하루/주간 개발 활동 통합 리포트 생성 툴

4개 데이터 소스 통합:
- screenpipe (화면 활동)
- git (커밋 이력)
- shell (명령어 패턴)
- browser (연구 활동)
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

# 다른 툴들 import
sys.path.insert(0, str(Path(__file__).parent))
from screen_search import run as screen_search_run
from git_daily_summary import run as git_summary_run
from shell_pattern_analyzer import run as shell_analyzer_run
from browser_research_digest import run as browser_digest_run

TOOL_SPEC = {
    "name": "workday_recap",
    "description": "하루 또는 주간 개발 활동을 통합 리포트로 생성합니다. screen/git/shell/browser 데이터를 종합합니다.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["daily", "weekly"],
                "description": "daily=오늘, weekly=최근 7일",
            },
            "repo_path": {
                "type": "string",
                "description": "Git 리포지토리 경로 (선택, 기본값: 현재 디렉토리)",
            },
            "focus_keyword": {
                "type": "string",
                "description": "화면 검색 키워드 (선택, 입력 시 해당 키워드 관련 활동만)",
            },
        },
        "required": ["mode"],
    },
}


def run(input_data: dict, context: dict) -> Any:
    """
    통합 리포트 생성

    Args:
        input_data: {"mode": "daily"|"weekly", "repo_path": "...", "focus_keyword": "..."}
        context: 실행 컨텍스트

    Returns:
        통합 리포트 dict
    """
    mode = input_data.get("mode", "daily")
    repo_path = input_data.get("repo_path", ".")
    focus_keyword = input_data.get("focus_keyword")

    days = 1 if mode == "daily" else 7
    hours_back = 24 if mode == "daily" else 168

    report = {
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "period": f"최근 {days}일",
        "sections": {},
        "errors": [],
    }

    # 1. Screen Activity (screenpipe) - focus_keyword가 있을 때만 실행
    if focus_keyword:
        try:
            screen_result = screen_search_run(
                {"query": focus_keyword, "content_type": "ocr", "hours_back": hours_back, "limit": 50},
                context
            )

            if screen_result.get("ok") is True:
                results = screen_result.get("results", [])
                apps = {}
                for r in results:
                    app = r.get("app_name", "Unknown")
                    apps[app] = apps.get(app, 0) + 1

                report["sections"]["screen"] = {
                    "total_captures": len(results),
                    "top_apps": sorted(apps.items(), key=lambda x: x[1], reverse=True)[:5],
                    "focus_keyword": focus_keyword,
                }
            else:
                report["errors"].append(f"screen_search 실패: {screen_result.get('error')}")
        except Exception as e:
            report["errors"].append(f"screen_search 예외: {str(e)}")

    # 2. Git Activity
    try:
        git_result = git_summary_run(
            {"repo_path": repo_path, "days": days},
            context
        )

        if git_result.get("ok") is True:
            report["sections"]["git"] = {
                "total_commits": git_result.get("total_commits", 0),
                "authors": git_result.get("authors", []),
                "files_changed": git_result.get("files_changed", 0),
                "insertions": git_result.get("insertions", 0),
                "deletions": git_result.get("deletions", 0),
                "active_branches": git_result.get("active_branches", []),
            }
        else:
            # Git 저장소가 아닌 경우는 에러로 표시하지 않음 (선택적 기능)
            pass
    except Exception as e:
        report["errors"].append(f"git_daily_summary 예외: {str(e)}")

    # 3. Shell Patterns
    try:
        shell_result = shell_analyzer_run(
            {"days": days},
            context
        )

        if shell_result.get("ok") is True:
            report["sections"]["shell"] = {
                "total_commands": shell_result.get("total_commands", 0),
                "unique_commands": shell_result.get("unique_commands", 0),
                "top_commands": shell_result.get("top_commands", [])[:10],
                "alias_suggestions": shell_result.get("alias_suggestions", [])[:5],
            }
        else:
            report["errors"].append(f"shell_pattern_analyzer 실패: {shell_result.get('error')}")
    except Exception as e:
        report["errors"].append(f"shell_pattern_analyzer 예외: {str(e)}")

    # 4. Browser Research
    try:
        browser_result = browser_digest_run(
            {"hours_back": hours_back},
            context
        )

        if browser_result.get("ok") is True:
            report["sections"]["browser"] = {
                "total_visits": browser_result.get("total_pages", 0),
                "unique_domains": browser_result.get("unique_domains", 0),
                "top_domains": browser_result.get("top_domains", [])[:10],
                "sessions": len(browser_result.get("sessions", [])),
            }
        else:
            report["errors"].append(f"browser_research_digest 실패: {browser_result.get('error')}")
    except Exception as e:
        report["errors"].append(f"browser_research_digest 예외: {str(e)}")

    # Summary 생성
    report["summary"] = _generate_summary(report)

    return {
        "status": "success",
        "report": report,
    }


def _generate_summary(report: dict) -> str:
    """리포트에서 한줄 요약 생성"""
    sections = report.get("sections", {})
    mode = report.get("mode", "daily")
    period = "오늘" if mode == "daily" else "이번 주"

    parts = []

    if "git" in sections:
        commits = sections["git"].get("total_commits", 0)
        if commits > 0:
            parts.append(f"커밋 {commits}개")

    if "shell" in sections:
        cmds = sections["shell"].get("total_commands", 0)
        if cmds > 0:
            parts.append(f"명령어 {cmds}개")

    if "browser" in sections:
        visits = sections["browser"].get("total_visits", 0)
        if visits > 0:
            parts.append(f"웹 방문 {visits}개")

    if "screen" in sections:
        captures = sections["screen"].get("total_captures", 0)
        if captures > 0:
            parts.append(f"화면 캡처 {captures}개")

    if parts:
        return f"{period} 활동: " + ", ".join(parts)
    else:
        return f"{period} 활동 데이터 없음"


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
        print(json.dumps({"error": "--tool-input-json is required"}, ensure_ascii=False))
        sys.exit(1)

    try:
        input_data = json.loads(args.tool_input_json)
        context = json.loads(args.tool_context_json)
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
