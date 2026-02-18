from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import glob
import json
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_path(workdir: Path, path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = (workdir / path).resolve()
    return path


def _safe_read_jsonl(path: Path, max_lines: int = 50000) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    rows: list[dict[str, Any]] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_iso_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_tool_name(row: dict[str, Any]) -> str:
    event = str(row.get("event", ""))
    if event != "tool_call":
        return ""
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        name = str(payload.get("tool", "")).strip()
        if name:
            return name
    return ""


def build_dashboard_snapshot(
    *,
    workdir: str,
    token_usage_file: str = "logs/token_usage.jsonl",
    recovery_metrics_file: str = "logs/recovery_metrics.jsonl",
    recovery_alert_file: str = "logs/recovery_alerts.jsonl",
    chat_log_glob: str = "logs/**/chat*.jsonl",
) -> dict[str, Any]:
    root = Path(workdir).resolve()
    token_path = _resolve_path(root, token_usage_file)
    recovery_path = _resolve_path(root, recovery_metrics_file)
    alert_path = _resolve_path(root, recovery_alert_file)

    token_rows = _safe_read_jsonl(token_path)
    recovery_rows = _safe_read_jsonl(recovery_path)
    alert_rows = _safe_read_jsonl(alert_path)

    chat_rows: list[dict[str, Any]] = []
    chat_pattern = str(_resolve_path(root, chat_log_glob))
    for candidate in sorted(glob.glob(chat_pattern, recursive=True))[-40:]:
        chat_rows.extend(_safe_read_jsonl(Path(candidate), max_lines=20000))

    token_input = sum(_coerce_int(r.get("input_tokens")) for r in token_rows)
    token_output = sum(_coerce_int(r.get("output_tokens")) for r in token_rows)
    token_total = sum(_coerce_int(r.get("total_tokens")) for r in token_rows)
    req_total = sum(_coerce_int(r.get("requests")) for r in token_rows)
    estimated_cost = sum(_coerce_float(r.get("estimated_cost_usd")) for r in token_rows)

    recovery_success = sum(1 for r in recovery_rows if bool(r.get("success")))
    recovery_total = len(recovery_rows)
    recovery_failure = max(0, recovery_total - recovery_success)
    recovery_rate = (recovery_success / recovery_total * 100.0) if recovery_total else 0.0

    tool_counter: Counter[str] = Counter()
    sessions: set[str] = set()
    now = _utc_now()
    recent_cutoff = now - timedelta(hours=24)
    events_24h = 0

    for row in chat_rows:
        name = _extract_tool_name(row)
        if name:
            tool_counter[name] += 1
        session_id = str(row.get("session_id", "")).strip()
        if session_id:
            sessions.add(session_id)
        ts = _parse_iso_ts(row.get("ts"))
        if ts is not None and ts >= recent_cutoff:
            events_24h += 1

    return {
        "generated_at": now.isoformat(),
        "token_usage": {
            "records": len(token_rows),
            "requests": req_total,
            "input_tokens": token_input,
            "output_tokens": token_output,
            "total_tokens": token_total,
            "estimated_cost_usd": round(estimated_cost, 8),
        },
        "recovery": {
            "records": recovery_total,
            "success": recovery_success,
            "failure": recovery_failure,
            "success_rate_pct": round(recovery_rate, 2),
            "alerts": len(alert_rows),
        },
        "chat": {
            "records": len(chat_rows),
            "sessions": len(sessions),
            "events_last_24h": events_24h,
            "top_tools": [{"name": name, "count": count} for name, count in tool_counter.most_common(5)],
        },
        "paths": {
            "token_usage_file": str(token_path),
            "recovery_metrics_file": str(recovery_path),
            "recovery_alert_file": str(alert_path),
            "chat_log_glob": chat_pattern,
        },
    }


def render_dashboard_text(snapshot: dict[str, Any]) -> str:
    token = snapshot.get("token_usage", {}) if isinstance(snapshot.get("token_usage"), dict) else {}
    recovery = snapshot.get("recovery", {}) if isinstance(snapshot.get("recovery"), dict) else {}
    chat = snapshot.get("chat", {}) if isinstance(snapshot.get("chat"), dict) else {}

    lines = ["운영 대시보드"]
    lines.append(f"생성 시각(UTC): {snapshot.get('generated_at', '')}")
    lines.append("")
    lines.append("[토큰/비용]")
    lines.append(
        "- 요청: {req}회, 입력: {inp:,}, 출력: {out:,}, 합계: {tot:,}, 추정비용: ${cost:.6f}".format(
            req=_coerce_int(token.get("requests")),
            inp=_coerce_int(token.get("input_tokens")),
            out=_coerce_int(token.get("output_tokens")),
            tot=_coerce_int(token.get("total_tokens")),
            cost=_coerce_float(token.get("estimated_cost_usd")),
        )
    )
    lines.append("[복구]")
    lines.append(
        "- 시도: {all_cnt}, 성공: {ok}, 실패: {fail}, 성공률: {rate:.2f}%, 알림: {alerts}".format(
            all_cnt=_coerce_int(recovery.get("records")),
            ok=_coerce_int(recovery.get("success")),
            fail=_coerce_int(recovery.get("failure")),
            rate=_coerce_float(recovery.get("success_rate_pct")),
            alerts=_coerce_int(recovery.get("alerts")),
        )
    )
    lines.append("[대화/도구]")
    lines.append(
        "- 로그: {records}건, 세션: {sessions}개, 최근24h 이벤트: {e24}건".format(
            records=_coerce_int(chat.get("records")),
            sessions=_coerce_int(chat.get("sessions")),
            e24=_coerce_int(chat.get("events_last_24h")),
        )
    )
    top_tools = chat.get("top_tools")
    if isinstance(top_tools, list) and top_tools:
        lines.append("- 상위 도구 호출:")
        for item in top_tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            count = _coerce_int(item.get("count"))
            if name:
                lines.append(f"  - {name}: {count}회")
    else:
        lines.append("- 상위 도구 호출: 없음")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BoramClaw metrics dashboard")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    snapshot = build_dashboard_snapshot(workdir=args.workdir)
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(render_dashboard_text(snapshot))
