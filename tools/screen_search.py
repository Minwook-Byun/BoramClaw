from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "screen_search",
    "description": "screenpipe를 통해 화면에서 본 내용(OCR)이나 음성(audio)을 검색합니다. 예: '3시간 전 본 에러 메시지', '어제 Slack에서 본 내용'",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "검색할 텍스트 (OCR/음성 전사 기반)",
            },
            "content_type": {
                "type": "string",
                "enum": ["ocr", "audio", "all"],
                "description": "검색 대상: ocr(화면), audio(음성), all(전체)",
            },
            "hours_back": {
                "type": "integer",
                "description": "현재 시점에서 몇 시간 전까지 검색할지 (기본 24시간)",
            },
            "app_name": {
                "type": "string",
                "description": "특정 앱에서 본 내용만 검색 (예: 'Chrome', 'VS Code')",
            },
            "limit": {
                "type": "integer",
                "description": "반환할 최대 결과 수 (기본 5)",
            },
        },
        "required": ["query"],
    },
}

SCREENPIPE_URL = os.environ.get("SCREENPIPE_API_URL", "http://localhost:3030")


def _health_check() -> dict:
    try:
        req = Request(f"{SCREENPIPE_URL}/health", method="GET")
        with urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError) as exc:
        return {"status": "unreachable", "error": str(exc)}


def _search(query: str, content_type: str = "all",
            hours_back: int = 24, app_name: str = "",
            limit: int = 5) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours_back)

    params: dict[str, Any] = {
        "q": query,
        "limit": limit,
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if content_type and content_type != "all":
        params["content_type"] = content_type
    if app_name:
        params["app_name"] = app_name

    url = f"{SCREENPIPE_URL}/search?{urlencode(params)}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _format_results(raw: dict) -> dict:
    """screenpipe 응답을 간결하게 가공"""
    data = raw.get("data", [])
    results = []
    for item in data:
        content = item.get("content", {})
        entry: dict[str, Any] = {
            "type": item.get("type", "unknown"),
            "timestamp": content.get("timestamp", ""),
        }
        if item.get("type") == "OCR":
            entry["app_name"] = content.get("app_name", "")
            entry["window_name"] = content.get("window_name", "")
            entry["text"] = content.get("text", "")[:500]
        elif item.get("type") == "Audio":
            entry["transcription"] = content.get("transcription", "")[:500]
            entry["device"] = content.get("device_name", "")
        results.append(entry)

    return {
        "ok": True,
        "count": len(results),
        "total": raw.get("pagination", {}).get("total", len(results)),
        "results": results,
    }


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    health = _health_check()
    if health.get("status") != "healthy":
        return {
            "ok": False,
            "error": "screenpipe가 실행 중이 아닙니다. `screenpipe` 명령으로 시작해주세요.",
            "health": health,
        }

    query = input_data.get("query", "")
    if not query.strip():
        return {"ok": False, "error": "검색어(query)가 비어 있습니다."}

    try:
        raw = _search(
            query=query,
            content_type=input_data.get("content_type", "all"),
            hours_back=input_data.get("hours_back", 24),
            app_name=input_data.get("app_name", ""),
            limit=input_data.get("limit", 5),
        )
        return _format_results(raw)
    except URLError as exc:
        return {"ok": False, "error": f"screenpipe API 오류: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"검색 실패: {exc}"}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="screen_search cli")
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
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
