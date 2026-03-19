#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from daily_retrospective import (
    append_retrospective_posts,
    build_daily_retrospective_markdown,
    build_retrospective_post,
    collect_daily_retrospective_evidence,
    write_retrospective_markdown,
)

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "daily_retrospective_post",
    "description": "Generate a detailed daily retrospective markdown and auto-post it into AutoDashboard.",
    "version": __version__,
    "network_access": False,
    "input_schema": {
        "type": "object",
        "properties": {
            "target_date": {
                "type": "string",
                "description": "Target local date in YYYY-MM-DD. Defaults to today.",
            },
            "history_file": {
                "type": "string",
                "description": "Codex history.jsonl path.",
            },
            "timeseries_file": {
                "type": "string",
                "description": "session_timeseries.jsonl path.",
            },
            "sessions_root": {
                "type": "string",
                "description": "Codex sessions root.",
            },
            "repo_roots": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit repo roots to scan for commit and file evidence.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to write markdown reports into.",
            },
            "posts_file": {
                "type": "string",
                "description": "AutoDashboard JSONL posts file.",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
            },
            "slot_ts": {
                "type": "string",
                "description": "Optional ISO timestamp used as the post slot key, e.g. 2026-03-13T11:00:00+09:00.",
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


def _resolve_path(raw: str, context: dict[str, Any], *, fallback_name: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        text = fallback_name
    target = Path(text).expanduser()
    if not target.is_absolute():
        target = (Path(str(context.get("workdir", ".")).strip() or Path.cwd()) / target).resolve()
    return target


def _repo_roots(input_data: dict[str, Any]) -> list[str]:
    raw = input_data.get("repo_roots")
    values: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                values.append(text)
    elif isinstance(raw, str):
        values.extend(piece.strip() for piece in raw.split(",") if piece.strip())
    env_value = str(os.getenv("BORAMCLAW_RETROSPECTIVE_REPO_ROOTS", "")).strip()
    if env_value:
        values.extend(piece.strip() for piece in env_value.split(",") if piece.strip())
    return list(dict.fromkeys(values))


def _parse_timestamp(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed.astimezone()


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    workdir = Path(str(context.get("workdir", ROOT_DIR)).strip() or ROOT_DIR).expanduser().resolve()
    target_date = str(input_data.get("target_date", "")).strip()
    if not target_date:
        target_date = datetime.now().astimezone().date().isoformat()
    history_file = _resolve_path(
        str(input_data.get("history_file", "")).strip() or os.getenv("BORAMCLAW_WRAPUP_HISTORY_FILE", ""),
        {"workdir": str(workdir)},
        fallback_name=str(Path.home() / ".codex" / "history.jsonl"),
    )
    timeseries_file = _resolve_path(
        str(input_data.get("timeseries_file", "")).strip() or os.getenv("SESSION_TIMESERIES_FILE", ""),
        {"workdir": str(workdir)},
        fallback_name="logs/session_timeseries.jsonl",
    )
    sessions_root = _resolve_path(
        str(input_data.get("sessions_root", "")).strip() or os.getenv("BORAMCLAW_CODEX_SESSIONS_ROOT", ""),
        {"workdir": str(workdir)},
        fallback_name=str(Path.home() / ".codex" / "sessions"),
    )
    output_dir = _resolve_path(
        str(input_data.get("output_dir", "")).strip() or os.getenv("BORAMCLAW_RETROSPECTIVE_OUTPUT_DIR", ""),
        {"workdir": str(workdir)},
        fallback_name="logs/reviews/daily",
    )
    posts_file = _resolve_path(
        str(input_data.get("posts_file", "")).strip() or os.getenv("AUTO_DASHBOARD_RETROSPECTIVE_POSTS_FILE", ""),
        {"workdir": str(workdir)},
        fallback_name=str(Path.home() / "Desktop" / "AutoDashboard" / "apps" / "web" / "app" / "dashboard" / "retrospectives" / "posts.jsonl"),
    )
    dry_run = bool(input_data.get("dry_run", False))
    slot_ts = _parse_timestamp(str(input_data.get("slot_ts", "")).strip())

    evidence = collect_daily_retrospective_evidence(
        target_date=target_date,
        workdir=workdir,
        history_file=history_file,
        timeseries_file=timeseries_file,
        sessions_root=sessions_root,
        repo_roots=_repo_roots(input_data),
    )
    markdown = build_daily_retrospective_markdown(evidence)
    post = build_retrospective_post(evidence=evidence, markdown=markdown, slot_ts=slot_ts)
    target_day = str(evidence.get("date", "")).strip()
    markdown_path = output_dir / f"daily_{target_day}.md"

    if dry_run:
        return {
            "ok": True,
            "status": "dry_run",
            "date": target_day,
            "markdown_path": str(markdown_path),
            "posts_file": str(posts_file),
            "summary": post.get("summary"),
            "repo_names": post.get("repo_names"),
            "prompt_count": post.get("prompt_count"),
            "session_count": post.get("session_count"),
            "markdown_preview": markdown[:600],
        }

    write_retrospective_markdown(markdown_path, markdown)
    inserted = append_retrospective_posts(posts_file, [post])

    return {
        "ok": True,
        "status": "posted",
        "date": target_day,
        "markdown_path": str(markdown_path),
        "posts_file": str(posts_file),
        "inserted": inserted,
        "post_id": post.get("post_id"),
        "summary": post.get("summary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=TOOL_SPEC["description"])
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
        result = run(input_data=input_data, context=context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
