from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import get_store, period_to_days


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "google_drive_pull",
    "description": "P1 scaffold for Google Drive manifest pull and sync-run logging.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "startup_id": {"type": "string"},
            "connection_id": {"type": "string"},
            "period": {"type": "string", "description": "today|7d|30d"},
            "window_from": {"type": "string"},
            "window_to": {"type": "string"},
            "folder_id": {"type": "string"},
            "max_files": {"type": "integer", "minimum": 1, "maximum": 2000},
            "dry_run": {"type": "boolean"},
            "auto_refresh": {"type": "boolean"},
            "min_valid_seconds": {"type": "integer", "minimum": 0},
        },
        "required": ["startup_id", "connection_id"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _resolve_window(input_data: dict[str, Any]) -> tuple[str, str]:
    window_from = str(input_data.get("window_from", "")).strip()
    window_to = str(input_data.get("window_to", "")).strip()
    if window_from and window_to:
        return window_from, window_to
    period = str(input_data.get("period", "7d")).strip().lower() or "7d"
    days = period_to_days(period)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on", "y"}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    startup_id = str(input_data.get("startup_id", "")).strip().lower()
    connection_id = str(input_data.get("connection_id", "")).strip()
    if not startup_id:
        return {"success": False, "error": "startup_id is required"}
    if not connection_id:
        return {"success": False, "error": "connection_id is required"}

    store = get_store(context)
    connection = store.get_integration_connection(connection_id)
    if connection is None:
        return {"success": False, "error": f"connection_id not found: {connection_id}"}
    status = str(connection.get("status", "")).strip().lower()
    if status == "revoked":
        return {"success": False, "error": f"connection is revoked: {connection_id}"}
    if status != "connected":
        return {"success": False, "error": f"connection status must be connected: {status or 'unknown'}"}

    auto_refresh = _as_bool(input_data.get("auto_refresh"), True)
    min_valid_seconds = int(input_data.get("min_valid_seconds", 120) or 120)
    refresh_result: dict[str, Any] | None = None
    if auto_refresh:
        from tools.google_oauth_connect import run as oauth_connect_run

        refresh_result = oauth_connect_run(
            {
                "action": "refresh_token",
                "connection_id": connection_id,
                "min_valid_seconds": max(0, min_valid_seconds),
            },
            context,
        )
        if not bool(refresh_result.get("success", False)):
            return {
                "success": False,
                "error": f"auto refresh failed: {refresh_result.get('error', 'unknown')}",
                "connection_id": connection_id,
            }

    window_from, window_to = _resolve_window(input_data)
    run_id = str(uuid4())
    dry_run = bool(input_data.get("dry_run", True))
    max_files = int(input_data.get("max_files", 300) or 300)
    max_files = max(1, min(max_files, 2000))
    folder_id = str(input_data.get("folder_id", "")).strip()

    store.create_integration_sync_run(
        run_id=run_id,
        startup_id=startup_id,
        provider="google_drive",
        connection_id=connection_id,
        run_mode=("dry_run" if dry_run else "pull"),
        window_from=window_from,
        window_to=window_to,
        status="running",
        summary={"planned_max_files": max_files, "folder_id": folder_id},
    )

    documents: list[dict[str, Any]] = []
    if not dry_run:
        # P1 scaffold: external API pull is intentionally deferred.
        documents = []
    summary = {
        "document_count": len(documents),
        "planned_max_files": max_files,
        "dry_run": dry_run,
        "folder_id": folder_id,
        "auto_refresh": auto_refresh,
        "refreshed": bool((refresh_result or {}).get("refreshed", False)),
        "notes": "P1 scaffold: Drive API fetch is not wired yet.",
    }
    store.finish_integration_sync_run(run_id=run_id, status="completed", summary=summary)

    return {
        "success": True,
        "run_id": run_id,
        "startup_id": startup_id,
        "provider": "google_drive",
        "window_from": window_from,
        "window_to": window_to,
        "dry_run": dry_run,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="google_drive_pull cli")
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
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
