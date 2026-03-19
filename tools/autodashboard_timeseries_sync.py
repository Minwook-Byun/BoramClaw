from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
import sys
import urllib.error
import urllib.request
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from session_timeseries import append_timeseries_rows, load_timeseries_rows

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "autodashboard_timeseries_sync",
    "description": "Send session timeseries rows from BoramClaw to AutoDashboard for daily accumulation.",
    "version": "1.0.0",
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "timeseries_file": {
                "type": "string",
                "description": "Path to local session_timeseries.jsonl",
            },
            "autodashboard_endpoint": {
                "type": "string",
                "description": "AutoDashboard endpoint that accepts {rows:[...]}",
            },
            "autodashboard_file": {
                "type": "string",
                "description": "Direct path to AutoDashboard snapshots.jsonl for offline/local sync",
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
                "description": "Timeseries kinds to sync (예: wrapup, codex_rollout)",
            },
            "max_rows": {
                "type": "integer",
                "minimum": 1,
                "default": 200,
                "description": "Max rows to sync per run",
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 3,
                "maximum": 90,
                "default": 20,
            },
            "fallback_file": {
                "type": "string",
                "description": "When sync fails, append payload here for retry",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
            },
            "not_before_ts": {
                "type": "string",
                "description": "Skip sync until this ISO timestamp is reached in local time",
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


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _parse_timestamp(raw: str) -> datetime | None:
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _ensure_local_timestamp(parsed: datetime | None) -> datetime | None:
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed.astimezone()


def _row_ts_key(row: dict[str, Any]) -> float:
    ts_raw = row.get("ts")
    if isinstance(ts_raw, str):
        parsed = _parse_timestamp(ts_raw)
        if parsed is not None:
            return parsed.timestamp()
    date_raw = row.get("date")
    if isinstance(date_raw, str):
        parsed_date = _parse_date(date_raw)
        if parsed_date is not None:
            return datetime.combine(parsed_date, datetime.min.time()).timestamp()
    return 0.0


def _coerce_kinds(raw: Any) -> list[str]:
    values: list[str] = []
    if raw is None:
        return values
    if isinstance(raw, str):
        values = [piece.strip() for piece in raw.split(",") if piece.strip()]
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if value:
                values.append(value)
    return values


def _append_fallback_rows(
    fallback_path: Path,
    endpoint: str,
    rows: list[dict[str, Any]],
    error: str,
) -> None:
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "error": error,
        "rows": rows,
    }
    with fallback_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _post_rows(
    endpoint: str,
    rows: list[dict[str, Any]],
    timeout_seconds: int,
) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps({"rows": rows}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, {"error": raw or str(exc)}
    except Exception as exc:
        raise RuntimeError(f"AutoDashboard 전송 실패: {exc}") from exc

    try:
        parsed: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw": raw}
    return 200, parsed


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    timeseries_file = _resolve_path(
        str(input_data.get("timeseries_file", "")).strip() or os.getenv("SESSION_TIMESERIES_FILE", ""),
        context,
        fallback_name="logs/session_timeseries.jsonl",
    )
    autodashboard_file_raw = str(input_data.get("autodashboard_file", "")).strip() or os.getenv(
        "AUTO_DASHBOARD_TIMESERIES_FILE",
        "",
    )
    endpoint = str(input_data.get("autodashboard_endpoint", "")).strip() or (
        os.getenv("AUTO_DASHBOARD_TIMESERIES_ENDPOINT")
        or "http://localhost:3000/api/dashboard/timeseries/append"
    )
    fallback_file = str(input_data.get("fallback_file", "")).strip() or os.getenv(
        "AUTO_DASHBOARD_TIMESERIES_FALLBACK_FILE",
    )
    kinds = _coerce_kinds(
        input_data.get("kinds")
        or os.getenv("AUTO_DASHBOARD_TIMESERIES_KINDS")
        or "wrapup,codex_rollout"
    )
    if not kinds:
        kinds = ["wrapup", "codex_rollout"]

    days_back = int(
        input_data.get("days_back")
        or os.getenv("AUTO_DASHBOARD_TIMESERIES_DAYS_BACK")
        or 14
    )
    if days_back <= 0:
        days_back = 14
    max_rows = int(
        input_data.get("max_rows")
        or os.getenv("AUTO_DASHBOARD_TIMESERIES_MAX_ROWS")
        or 200
    )
    if max_rows <= 0:
        max_rows = 200
    timeout_seconds = int(
        input_data.get("timeout_seconds")
        or os.getenv("AUTO_DASHBOARD_TIMESERIES_TIMEOUT_SECONDS")
        or 20
    )
    timeout_seconds = max(3, min(timeout_seconds, 90))
    dry_run = bool(input_data.get("dry_run", False))
    not_before_raw = str(input_data.get("not_before_ts", "")).strip() or os.getenv(
        "AUTO_DASHBOARD_TIMESERIES_NOT_BEFORE",
        "",
    )

    now = datetime.now(timezone.utc).astimezone()
    not_before_ts = _ensure_local_timestamp(_parse_timestamp(not_before_raw)) if not_before_raw else None
    if not_before_ts is not None and now < not_before_ts:
        return {
            "ok": True,
            "status": "skipped_not_before",
            "not_before_ts": not_before_ts.isoformat(),
            "now": now.isoformat(),
            "timeseries_file": str(timeseries_file),
        }

    start_date = now.date() - timedelta(days=days_back - 1)
    selected_rows_raw = load_timeseries_rows(
        timeseries_file,
        start_date=start_date.isoformat(),
        kinds=kinds,
    )
    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in selected_rows_raw:
        if not isinstance(row, dict):
            continue
        snapshot_id = str(row.get("snapshot_id", "")).strip()
        if not snapshot_id:
            continue
        prev = rows_by_id.get(snapshot_id)
        if prev is None:
            rows_by_id[snapshot_id] = row
            continue
        if _row_ts_key(row) >= _row_ts_key(prev):
            rows_by_id[snapshot_id] = row

    rows = sorted(rows_by_id.values(), key=_row_ts_key)
    if len(rows) > max_rows:
        rows = rows[-max_rows:]

    if not rows:
        return {
            "ok": True,
            "status": "no_rows",
            "timeseries_file": str(timeseries_file),
            "autodashboard_endpoint": endpoint,
            "kinds": kinds,
            "days_back": days_back,
        }

    if dry_run:
        return {
            "ok": True,
            "status": "dry_run",
            "rows": len(rows),
            "sample_snapshot_ids": [row.get("snapshot_id") for row in rows[:3]],
            "timeseries_file": str(timeseries_file),
            "autodashboard_file": autodashboard_file_raw,
            "autodashboard_endpoint": endpoint,
            "kinds": kinds,
            "days_back": days_back,
        }

    if autodashboard_file_raw:
        autodashboard_file = _resolve_path(
            autodashboard_file_raw,
            context,
            fallback_name="app/dashboard/timeseries/snapshots.jsonl",
        )
        inserted = append_timeseries_rows(autodashboard_file, rows)
        return {
            "ok": True,
            "status": "synced_file",
            "mode": "file",
            "synced_rows": len(rows),
            "inserted": inserted,
            "autodashboard_file": str(autodashboard_file),
            "sample_snapshot_ids": [row.get("snapshot_id") for row in rows[:3]],
            "timeseries_file": str(timeseries_file),
            "kinds": kinds,
            "days_back": days_back,
        }

    code, response = _post_rows(endpoint=endpoint, rows=rows, timeout_seconds=timeout_seconds)
    if code >= 400:
        fallback_written = False
        if fallback_file:
            try:
                fallback_path = _resolve_path(
                    fallback_file,
                    context,
                    fallback_name="logs/session_timeseries_sync_fallback.jsonl",
                )
                _append_fallback_rows(
                    fallback_path=fallback_path,
                    endpoint=endpoint,
                    rows=rows,
                    error=str((response.get("error") if isinstance(response, dict) else "http_error")),
                )
                fallback_written = True
            except Exception as exc:
                return {
                    "ok": False,
                    "status": "error",
                    "message": f"HTTP {code} and fallback write failed: {exc}",
                    "autodashboard_endpoint": endpoint,
                    "response": response,
                    "rows": len(rows),
                }
        return {
            "ok": False,
            "status": "error",
            "message": f"AutoDashboard endpoint returned HTTP {code}",
            "http_status": code,
            "autodashboard_endpoint": endpoint,
            "response": response,
            "fallback_written": fallback_written,
            "rows": len(rows),
        }

    return {
        "ok": True,
        "status": "synced",
        "synced_rows": len(rows),
        "autodashboard_endpoint": endpoint,
        "response": response,
        "sample_snapshot_ids": [row.get("snapshot_id") for row in rows[:3]],
        "timeseries_file": str(timeseries_file),
        "kinds": kinds,
        "days_back": days_back,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="autodashboard_timeseries_sync cli")
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
