#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from codex_adapter import CodexCLIError, CodexRunner, build_wrapup_prompt, is_codex_command_available
from session_timeseries import (
    append_timeseries_rows,
    build_wrapup_snapshot,
    collect_codex_rollout_snapshots,
)
from tools.autodashboard_timeseries_sync import run as run_autodashboard_sync
from tools.daily_retrospective_post import run as run_daily_retrospective_post
from wrapup_evidence import collect_wrapup_evidence, render_wrapup_fallback

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "daily_wrapup_pipeline",
    "description": "Backfill Codex rollout stats, generate an evidence-first daily wrapup, and sync it into AutoDashboard.",
    "version": __version__,
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "description": "Optional focus for the daily wrapup.",
            },
            "timeseries_file": {
                "type": "string",
                "description": "Path to BoramClaw session_timeseries.jsonl.",
            },
            "history_file": {
                "type": "string",
                "description": "Path to Codex history.jsonl used for prompt evidence.",
            },
            "sessions_root": {
                "type": "string",
                "description": "Root directory for Codex rollout session files.",
            },
            "autodashboard_file": {
                "type": "string",
                "description": "Direct snapshots.jsonl path for local/offline AutoDashboard sync.",
            },
            "autodashboard_endpoint": {
                "type": "string",
                "description": "Append endpoint for AutoDashboard sync.",
            },
            "days_back": {
                "type": "integer",
                "minimum": 1,
                "default": 14,
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["wrapup", "codex_rollout"],
            },
            "max_rows": {
                "type": "integer",
                "minimum": 1,
                "default": 200,
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 3,
                "maximum": 90,
                "default": 20,
            },
            "codex_timeout_seconds": {
                "type": "integer",
                "minimum": 10,
                "maximum": 600,
                "default": 180,
            },
            "backfill_rollouts": {
                "type": "boolean",
                "default": True,
            },
            "sync_after": {
                "type": "boolean",
                "default": True,
            },
            "post_retrospective": {
                "type": "boolean",
                "default": True,
            },
            "retrospective_output_dir": {
                "type": "string",
                "description": "Directory to write detailed retrospective markdown files into.",
            },
            "retrospective_posts_file": {
                "type": "string",
                "description": "AutoDashboard JSONL file for retrospective posts.",
            },
            "retrospective_repo_roots": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit repo roots for retrospective evidence collection.",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
            },
            "not_before_ts": {
                "type": "string",
                "description": "Skip entire pipeline until this ISO timestamp in local time.",
            },
            "slot_ts": {
                "type": "string",
                "description": "Optional ISO timestamp used as the hourly slot key and stored ts.",
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


def _coerce_kinds(raw: Any) -> list[str]:
    values: list[str] = []
    if raw is None:
        return values
    if isinstance(raw, str):
        values = [piece.strip() for piece in raw.split(",") if piece.strip()]
    elif isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                values.append(text)
    return values


def _generate_wrapup(
    *,
    workdir: Path,
    focus: str,
    command: str,
    model: str,
    session_memory: list[str],
    evidence: dict[str, Any],
    codex_timeout_seconds: int,
) -> tuple[str, str]:
    if is_codex_command_available(command):
        runner = CodexRunner(command=command, model=model, workdir=str(workdir))
        prompt = build_wrapup_prompt(session_memory=session_memory, focus=focus, evidence=evidence)
        try:
            return "codex", runner.exec_prompt(prompt, timeout_seconds=max(10, min(codex_timeout_seconds, 600)))
        except CodexCLIError:
            pass
    return "fallback", render_wrapup_fallback(evidence=evidence, focus=focus)


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    workdir = Path(str(context.get("workdir", ROOT_DIR)).strip() or ROOT_DIR).expanduser().resolve()
    timeseries_file = _resolve_path(
        str(input_data.get("timeseries_file", "")).strip() or os.getenv("SESSION_TIMESERIES_FILE", ""),
        {"workdir": str(workdir)},
        fallback_name="logs/session_timeseries.jsonl",
    )
    history_file = _resolve_path(
        str(input_data.get("history_file", "")).strip() or os.getenv("BORAMCLAW_WRAPUP_HISTORY_FILE", ""),
        {"workdir": str(workdir)},
        fallback_name=str(Path.home() / ".codex" / "history.jsonl"),
    )
    sessions_root = _resolve_path(
        str(input_data.get("sessions_root", "")).strip() or os.getenv("BORAMCLAW_CODEX_SESSIONS_ROOT", ""),
        {"workdir": str(workdir)},
        fallback_name=str(Path.home() / ".codex" / "sessions"),
    )

    focus = (
        str(input_data.get("focus", "")).strip()
        or os.getenv("BORAMCLAW_WRAPUP_DAILY_FOCUS", "").strip()
        or "OpenClaw식 일일 회고와 다음 세션 첫 TODO 정리"
    )
    kinds = _coerce_kinds(
        input_data.get("kinds")
        or os.getenv("AUTO_DASHBOARD_TIMESERIES_KINDS")
        or "wrapup,codex_rollout"
    )
    if not kinds:
        kinds = ["wrapup", "codex_rollout"]

    days_back = int(input_data.get("days_back") or os.getenv("AUTO_DASHBOARD_TIMESERIES_DAYS_BACK") or 14)
    max_rows = int(input_data.get("max_rows") or os.getenv("AUTO_DASHBOARD_TIMESERIES_MAX_ROWS") or 200)
    timeout_seconds = int(input_data.get("timeout_seconds") or os.getenv("AUTO_DASHBOARD_TIMESERIES_TIMEOUT_SECONDS") or 20)
    codex_timeout_seconds = int(
        input_data.get("codex_timeout_seconds")
        or os.getenv("BORAMCLAW_WRAPUP_CODEX_TIMEOUT_SECONDS")
        or 180
    )
    backfill_rollouts = bool(input_data.get("backfill_rollouts", True))
    sync_after = bool(input_data.get("sync_after", True))
    post_retrospective = bool(input_data.get("post_retrospective", True))
    retrospective_output_dir = str(input_data.get("retrospective_output_dir", "")).strip() or os.getenv(
        "BORAMCLAW_RETROSPECTIVE_OUTPUT_DIR",
        "",
    )
    retrospective_posts_file = str(input_data.get("retrospective_posts_file", "")).strip() or os.getenv(
        "AUTO_DASHBOARD_RETROSPECTIVE_POSTS_FILE",
        "",
    )
    retrospective_repo_roots = input_data.get("retrospective_repo_roots") or os.getenv(
        "BORAMCLAW_RETROSPECTIVE_REPO_ROOTS",
        "",
    )
    dry_run = bool(input_data.get("dry_run", False))
    not_before_raw = str(input_data.get("not_before_ts", "")).strip() or os.getenv("AUTO_DASHBOARD_TIMESERIES_NOT_BEFORE", "")
    autodashboard_file = str(input_data.get("autodashboard_file", "")).strip() or os.getenv("AUTO_DASHBOARD_TIMESERIES_FILE", "")
    autodashboard_endpoint = str(input_data.get("autodashboard_endpoint", "")).strip() or os.getenv(
        "AUTO_DASHBOARD_TIMESERIES_ENDPOINT",
        "http://localhost:3000/api/dashboard/timeseries/append",
    )
    fallback_file = str(input_data.get("fallback_file", "")).strip() or os.getenv(
        "AUTO_DASHBOARD_TIMESERIES_FALLBACK_FILE",
        "",
    )

    slot_ts_raw = str(input_data.get("slot_ts", "")).strip()
    slot_ts = _parse_timestamp(slot_ts_raw) if slot_ts_raw else None
    now = slot_ts or datetime.now(timezone.utc).astimezone()
    not_before_ts = _parse_timestamp(not_before_raw)
    if not_before_ts is not None and now < not_before_ts:
        return {
            "ok": True,
            "status": "skipped_not_before",
            "now": now.isoformat(),
            "not_before_ts": not_before_ts.isoformat(),
        }

    today = now.date().isoformat()
    appended_rollouts = 0
    rollout_rows: list[dict[str, Any]] = []
    if backfill_rollouts:
        rollout_rows = collect_codex_rollout_snapshots(
            start_date=today,
            end_date=today,
            sessions_root=sessions_root,
        )
        if rollout_rows:
            appended_rollouts = append_timeseries_rows(timeseries_file, rollout_rows)

    evidence = collect_wrapup_evidence(
        workdir=workdir,
        session_memory=[],
        timeseries_file=timeseries_file,
        history_file=history_file,
        now=now,
    )
    wrapup_mode, answer = _generate_wrapup(
        workdir=workdir,
        focus=focus,
        command=os.getenv("CODEX_COMMAND", "codex"),
        model=os.getenv("CODEX_MODEL", ""),
        session_memory=evidence.get("session_memory_tail", []) if isinstance(evidence.get("session_memory_tail"), list) else [],
        evidence=evidence,
        codex_timeout_seconds=codex_timeout_seconds,
    )

    snapshot = build_wrapup_snapshot(
        session_id=f"daily-wrapup-{today}",
        provider="codex" if wrapup_mode == "codex" else "heuristic",
        model=os.getenv("CODEX_MODEL", "") or ("codex-default" if wrapup_mode == "codex" else "fallback"),
        focus=focus,
        answer=answer,
        session_memory=evidence.get("session_memory_tail", []) if isinstance(evidence.get("session_memory_tail"), list) else [],
        usage={},
        ts=now,
        evidence=evidence,
        snapshot_key=f"auto:{now.strftime('%Y-%m-%dT%H')}",
    )
    snapshot["wrapup_mode"] = wrapup_mode
    snapshot["auto_generated"] = True
    snapshot["source"] = "daily_wrapup_pipeline"

    if dry_run:
        retrospective_preview = None
        if post_retrospective:
            retrospective_preview = run_daily_retrospective_post(
                {
                    "target_date": today,
                    "slot_ts": now.isoformat(),
                    "timeseries_file": str(timeseries_file),
                    "history_file": str(history_file),
                    "sessions_root": str(sessions_root),
                    "output_dir": retrospective_output_dir,
                    "posts_file": retrospective_posts_file,
                    "repo_roots": retrospective_repo_roots,
                    "dry_run": True,
                },
                {"workdir": str(workdir)},
            )
        return {
            "ok": True,
            "status": "dry_run",
            "date": today,
            "focus": focus,
            "wrapup_mode": wrapup_mode,
            "answer_preview": answer[:300],
            "prompt_count": int(evidence.get("prompt_count", 0) or 0),
            "repo_names": evidence.get("repo_names", []),
            "rollout_rows": len(rollout_rows),
            "appended_rollouts": appended_rollouts,
            "retrospective_preview": retrospective_preview,
        }

    append_timeseries_rows(timeseries_file, [snapshot])

    sync_result: dict[str, Any] | None = None
    if sync_after:
        sync_result = run_autodashboard_sync(
            {
                "timeseries_file": str(timeseries_file),
                "autodashboard_file": autodashboard_file,
                "autodashboard_endpoint": autodashboard_endpoint,
                "fallback_file": fallback_file,
                "days_back": max(1, days_back),
                "kinds": kinds,
                "max_rows": max(1, max_rows),
                "timeout_seconds": max(3, min(timeout_seconds, 90)),
            },
            {"workdir": str(workdir)},
        )

    retrospective_result: dict[str, Any] | None = None
    if post_retrospective:
        retrospective_result = run_daily_retrospective_post(
            {
                "target_date": today,
                "slot_ts": now.isoformat(),
                "timeseries_file": str(timeseries_file),
                "history_file": str(history_file),
                "sessions_root": str(sessions_root),
                "output_dir": retrospective_output_dir,
                "posts_file": retrospective_posts_file,
                "repo_roots": retrospective_repo_roots,
            },
            {"workdir": str(workdir)},
        )

    return {
        "ok": True,
        "status": "completed",
        "date": today,
        "focus": focus,
        "wrapup_mode": wrapup_mode,
        "snapshot_id": snapshot["snapshot_id"],
        "prompt_count": int(evidence.get("prompt_count", 0) or 0),
        "repo_names": evidence.get("repo_names", []),
        "appended_rollouts": appended_rollouts,
        "sync_result": sync_result,
        "retrospective_result": retrospective_result,
        "timeseries_file": str(timeseries_file),
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
