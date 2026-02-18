from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import urllib.parse
import urllib.request
from typing import Any

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "google_calendar_agenda",
    "description": "Fetch upcoming events from Google Calendar and summarize agenda in Korean.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "default": "primary",
                "description": "Google Calendar id",
            },
            "days": {
                "type": "integer",
                "default": 1,
                "description": "How many days ahead to read",
            },
            "max_events": {
                "type": "integer",
                "default": 10,
                "description": "Maximum events to return",
            },
            "query": {
                "type": "string",
                "description": "Keyword filter for summary/description",
            },
            "output": {
                "type": "string",
                "enum": ["text", "json"],
                "default": "text",
            },
        },
        "required": [],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_event(item: dict[str, Any]) -> dict[str, Any]:
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    end = item.get("end") if isinstance(item.get("end"), dict) else {}
    return {
        "id": str(item.get("id", "")),
        "summary": str(item.get("summary", "")).strip(),
        "start": str((start or {}).get("dateTime") or (start or {}).get("date") or "").strip(),
        "end": str((end or {}).get("dateTime") or (end or {}).get("date") or "").strip(),
        "location": str(item.get("location", "")).strip(),
        "html_link": str(item.get("htmlLink", "")).strip(),
    }


def _fetch_events_with_api_key(
    *,
    calendar_id: str,
    api_key: str,
    time_min: str,
    time_max: str,
    max_events: int,
) -> list[dict[str, Any]]:
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(max_events),
        "key": api_key,
    }
    encoded = urllib.parse.urlencode(params)
    cal_encoded = urllib.parse.quote(calendar_id, safe="")
    url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_encoded}/events?{encoded}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    items = parsed.get("items") if isinstance(parsed, dict) else []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _fetch_events_with_oauth(
    *,
    calendar_id: str,
    token_file: str,
    time_min: str,
    time_max: str,
    max_events: int,
) -> list[dict[str, Any]]:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(token_file)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_events,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    items = response.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _build_summary(calendar_id: str, events: list[dict[str, Any]]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# Calendar Agenda ({today})", f"Calendar: {calendar_id}", f"Events: {len(events)}", ""]
    if not events:
        lines.append("조회된 일정이 없습니다.")
        return "\n".join(lines)
    for idx, event in enumerate(events, start=1):
        lines.append(f"## {idx}. {event.get('summary', '(제목 없음)')}")
        lines.append(f"- 시작: {event.get('start', '-')}")
        lines.append(f"- 종료: {event.get('end', '-')}")
        location = str(event.get("location", "")).strip()
        if location:
            lines.append(f"- 장소: {location}")
        link = str(event.get("html_link", "")).strip()
        if link:
            lines.append(f"- 링크: {link}")
        lines.append("")
    return "\n".join(lines)


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    calendar_id = str(input_data.get("calendar_id") or os.getenv("GOOGLE_CALENDAR_ID") or "primary").strip()
    days = max(1, min(int(input_data.get("days", 1) or 1), 30))
    max_events = max(1, min(int(input_data.get("max_events", 10) or 10), 50))
    query = str(input_data.get("query", "")).strip().lower()
    output = str(input_data.get("output", "text")).strip().lower()

    now = datetime.now(timezone.utc)
    time_min = _iso_utc(now)
    time_max = _iso_utc(now + timedelta(days=days))

    events_raw: list[dict[str, Any]]
    token_file = str(os.getenv("GOOGLE_CALENDAR_TOKEN_FILE") or "").strip()
    api_key = str(os.getenv("GOOGLE_CALENDAR_API_KEY") or "").strip()

    if token_file:
        events_raw = _fetch_events_with_oauth(
            calendar_id=calendar_id,
            token_file=token_file,
            time_min=time_min,
            time_max=time_max,
            max_events=max_events,
        )
    elif api_key:
        events_raw = _fetch_events_with_api_key(
            calendar_id=calendar_id,
            api_key=api_key,
            time_min=time_min,
            time_max=time_max,
            max_events=max_events,
        )
    else:
        return {
            "ok": False,
            "error": "Google Calendar 인증 정보가 없습니다. GOOGLE_CALENDAR_TOKEN_FILE 또는 GOOGLE_CALENDAR_API_KEY를 설정하세요.",
        }

    normalized = [_normalize_event(item) for item in events_raw]
    if query:
        normalized = [
            item
            for item in normalized
            if query in f"{item.get('summary', '')} {item.get('location', '')}".lower()
        ]

    summary = _build_summary(calendar_id=calendar_id, events=normalized)
    payload = {
        "ok": True,
        "calendar_id": calendar_id,
        "count": len(normalized),
        "summary": summary,
        "events": normalized,
    }
    if output == "json":
        return payload
    return {
        "ok": True,
        "calendar_id": calendar_id,
        "count": len(normalized),
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="google_calendar_agenda cli")
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
        print(json.dumps(run(input_data, context), ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
