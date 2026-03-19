from __future__ import annotations

import argparse
from html import escape
import json
import shlex
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from turn_feedback import summarize_turn_feedback


THEME_RULES: dict[str, tuple[str, ...]] = {
    "repo_worktree": ("worktree", "repo", "repository", "branch", "commit", "git", "레포", "브랜치", "커밋", "작업트리", "디렉토리"),
    "auth": ("auth", "login", "oauth", "firebase", "emulator", "인증", "로그인", "에뮬레이터"),
    "deploy_env": ("deploy", "deployment", "preview", "vercel", "env", "production", "배포", "프리뷰", "환경"),
    "evidence_drive": ("evidence", "drive", "upload", "folder", "sheet", "document", "증빙", "드라이브", "업로드", "폴더"),
    "ux_product": ("ux", "ui", "flow", "modal", "screen", "onboarding", "사용자 흐름", "선택", "상태"),
    "parser_automation": ("parser", "parse", "nova", "hwpx", "extract", "automation", "파서", "파싱", "추출", "자동화"),
}


def _parse_timestamp(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _as_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt.astimezone()


def _coerce_date(raw: str | date | datetime) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw))


def _date_range(start_date: date, end_date: date) -> Iterable[date]:
    cursor = start_date
    while cursor <= end_date:
        yield cursor
        cursor += timedelta(days=1)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def _safe_command_head(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return "(empty)"
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    return parts[0] if parts else "(empty)"


def _extract_exec_command_payloads(tool_name: str, raw_arguments: Any) -> list[dict[str, Any]]:
    arguments: dict[str, Any] = {}
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            arguments = parsed
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments

    if tool_name == "exec_command":
        return [arguments] if arguments else []

    if tool_name in {"parallel", "multi_tool_use.parallel"}:
        payloads: list[dict[str, Any]] = []
        tool_uses = arguments.get("tool_uses", [])
        if isinstance(tool_uses, list):
            for item in tool_uses:
                if not isinstance(item, dict):
                    continue
                if str(item.get("recipient_name", "")).strip() != "functions.exec_command":
                    continue
                parameters = item.get("parameters", {})
                if isinstance(parameters, dict):
                    payloads.append(parameters)
        return payloads

    return []


def _theme_counts(messages: Iterable[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for message in messages:
        lowered = str(message or "").lower()
        if not lowered:
            continue
        for theme, keywords in THEME_RULES.items():
            if any(keyword.lower() in lowered for keyword in keywords):
                counts[theme] += 1
    return dict(counts)


def _top_rows(counter: Counter[str], *, label: str, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, count in counter.most_common(limit):
        rows.append({label: key, "count": int(count)})
    return rows


def _duration_minutes(started_at: datetime | None, ended_at: datetime | None) -> float:
    if started_at is None or ended_at is None:
        return 0.0
    seconds = max(0.0, (ended_at - started_at).total_seconds())
    return round(seconds / 60.0, 1)


def summarize_codex_rollout(path: str | Path) -> dict[str, Any]:
    rollout_path = Path(path).expanduser().resolve()
    rows = list(_iter_jsonl(rollout_path))
    if not rows:
        raise ValueError(f"빈 Codex session 파일입니다: {rollout_path}")

    started_at: datetime | None = None
    ended_at: datetime | None = None
    session_id = ""
    cwd = ""
    model = ""
    approval_policy = ""
    sandbox_mode = ""

    user_prompts: list[str] = []
    user_prompt_rows: list[dict[str, Any]] = []
    assistant_messages = 0
    commentary_messages = 0
    exec_payloads: list[dict[str, Any]] = []
    tool_calls: Counter[str] = Counter()

    for row in rows:
        row_ts = _parse_timestamp(row.get("timestamp", ""))
        if row_ts is not None:
            started_at = row_ts if started_at is None else min(started_at, row_ts)
            ended_at = row_ts if ended_at is None else max(ended_at, row_ts)

        row_type = str(row.get("type", "")).strip()
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        if row_type == "session_meta":
            session_id = str(payload.get("id", session_id)).strip() or session_id
            cwd = str(payload.get("cwd", cwd)).strip() or cwd
        elif row_type == "turn_context":
            model = str(payload.get("model", model)).strip() or model
            approval_policy = str(payload.get("approval_policy", approval_policy)).strip() or approval_policy
            sandbox_policy = payload.get("sandbox_policy", {})
            if isinstance(sandbox_policy, dict):
                sandbox_mode = str(sandbox_policy.get("type", sandbox_mode)).strip() or sandbox_mode
        elif row_type == "event_msg":
            event_type = str(payload.get("type", "")).strip()
            if event_type == "user_message":
                message = str(payload.get("message", "")).strip()
                if message:
                    user_prompts.append(message)
                    user_prompt_rows.append(
                        {
                            "session_id": session_id or rollout_path.stem,
                            "ts": row.get("timestamp", ""),
                            "text": message,
                        }
                    )
            elif event_type == "agent_message" and str(payload.get("phase", "")).strip() == "commentary":
                commentary_messages += 1
        elif row_type == "response_item":
            item_type = str(payload.get("type", "")).strip()
            if item_type == "message" and str(payload.get("role", "")).strip() == "assistant":
                if str(payload.get("phase", "")).strip() != "commentary":
                    assistant_messages += 1
            elif item_type == "function_call":
                tool_name = str(payload.get("name", "")).strip()
                if tool_name:
                    tool_calls[tool_name] += 1
                exec_payloads.extend(_extract_exec_command_payloads(tool_name, payload.get("arguments", {})))

    prompt_lengths = [len(text) for text in user_prompts]
    command_heads: Counter[str] = Counter()
    workdirs: Counter[str] = Counter()
    for item in exec_payloads:
        command_heads[_safe_command_head(str(item.get("cmd", "")))] += 1
        workdir = str(item.get("workdir", "")).strip() or cwd
        if workdir:
            workdirs[workdir] += 1

    primary_timestamp = started_at or ended_at
    local_primary = _as_local(primary_timestamp)
    local_started = _as_local(started_at)
    local_ended = _as_local(ended_at)
    date_key = local_primary.date().isoformat() if local_primary is not None else rollout_path.parent.name
    snapshot_id = f"codex_rollout:{session_id or rollout_path.stem}:{rollout_path.name}"
    feedback_summary = summarize_turn_feedback(user_prompt_rows)

    return {
        "snapshot_id": snapshot_id,
        "kind": "codex_rollout",
        "provider": "codex",
        "session_id": session_id or rollout_path.stem,
        "source_file": str(rollout_path),
        "date": date_key,
        "ts": (local_primary.isoformat() if local_primary is not None else ""),
        "started_at": (local_started.isoformat() if local_started is not None else ""),
        "ended_at": (local_ended.isoformat() if local_ended is not None else ""),
        "duration_minutes": _duration_minutes(started_at, ended_at),
        "cwd": cwd,
        "model": model,
        "approval_policy": approval_policy,
        "sandbox_mode": sandbox_mode,
        "user_prompt_count": len(user_prompts),
        "assistant_message_count": assistant_messages,
        "commentary_count": commentary_messages,
        "tool_call_count": sum(tool_calls.values()),
        "exec_command_count": len(exec_payloads),
        "prompt_chars_avg": round((sum(prompt_lengths) / len(prompt_lengths)), 1) if prompt_lengths else 0.0,
        "prompt_chars_median": float(statistics.median(prompt_lengths)) if prompt_lengths else 0.0,
        "short_prompt_count": sum(1 for size in prompt_lengths if size <= 10),
        "long_prompt_count": sum(1 for size in prompt_lengths if size >= 120),
        "feedback_prompt_count": int(feedback_summary.get("feedback_prompt_count", 0) or 0),
        "feedback_counts": feedback_summary.get("feedback_counts", {}),
        "feedback_rates": feedback_summary.get("feedback_rates", {}),
        "top_correction_hints": feedback_summary.get("top_correction_hints", []),
        "recent_feedback": feedback_summary.get("recent_feedback", []),
        "top_command_heads": _top_rows(command_heads, label="command"),
        "top_workdirs": _top_rows(workdirs, label="workdir"),
        "tool_call_breakdown": dict(tool_calls),
        "theme_counts": _theme_counts(user_prompts),
        "prompt_samples": [text[:160] for text in user_prompts[:5]],
    }


def build_wrapup_snapshot(
    *,
    session_id: str,
    provider: str,
    model: str,
    focus: str,
    answer: str,
    session_memory: list[str],
    usage: dict[str, Any] | None = None,
    ts: datetime | None = None,
    evidence: dict[str, Any] | None = None,
    snapshot_key: str = "",
) -> dict[str, Any]:
    timestamp = ts or datetime.now().astimezone()
    local_ts = _as_local(timestamp)
    normalized_memory = [str(item) for item in session_memory if str(item).strip()]
    user_messages = [item for item in normalized_memory if item.lower().startswith("user:")]
    assistant_messages = [item for item in normalized_memory if item.lower().startswith("assistant:")]
    lengths = [len(item) for item in normalized_memory]
    evidence_payload = dict(evidence or {})
    touched_repos = [
        item
        for item in evidence_payload.get("touched_repos", [])
        if isinstance(item, dict)
    ]
    prompt_samples = [str(item) for item in evidence_payload.get("prompt_samples", []) if str(item).strip()]
    active_workdirs = [str(item) for item in evidence_payload.get("active_workdirs", []) if str(item).strip()]
    git_totals = evidence_payload.get("git_totals", {}) if isinstance(evidence_payload.get("git_totals", {}), dict) else {}
    feedback_counts = evidence_payload.get("feedback_counts", {}) if isinstance(evidence_payload.get("feedback_counts", {}), dict) else {}
    feedback_rates = evidence_payload.get("feedback_rates", {}) if isinstance(evidence_payload.get("feedback_rates", {}), dict) else {}
    top_correction_hints = [
        item for item in evidence_payload.get("top_correction_hints", []) if isinstance(item, dict)
    ]
    recent_feedback = [item for item in evidence_payload.get("recent_feedback", []) if isinstance(item, dict)]
    snapshot_id = f"wrapup:{snapshot_key.strip()}" if snapshot_key.strip() else f"wrapup:{session_id}:{timestamp.isoformat()}"

    snapshot = {
        "snapshot_id": snapshot_id,
        "kind": "wrapup",
        "provider": provider,
        "session_id": session_id,
        "date": (local_ts.date().isoformat() if local_ts is not None else ""),
        "ts": (local_ts.isoformat() if local_ts is not None else ""),
        "model": model,
        "focus": focus.strip(),
        "summary": str(answer or "").strip(),
        "memory_entry_count": len(normalized_memory),
        "user_memory_count": len(user_messages),
        "assistant_memory_count": len(assistant_messages),
        "memory_chars_total": sum(lengths),
        "memory_chars_avg": round((sum(lengths) / len(lengths)), 1) if lengths else 0.0,
        "theme_counts": _theme_counts(normalized_memory),
        "prompt_count": int(evidence_payload.get("prompt_count", 0) or 0),
        "prompt_samples": prompt_samples[:8],
        "feedback_prompt_count": int(evidence_payload.get("feedback_prompt_count", 0) or 0),
        "feedback_counts": {
            "accepted": int(feedback_counts.get("accepted", 0) or 0),
            "corrected": int(feedback_counts.get("corrected", 0) or 0),
            "retried": int(feedback_counts.get("retried", 0) or 0),
            "ambiguous": int(feedback_counts.get("ambiguous", 0) or 0),
        },
        "feedback_rates": {
            "accepted": float(feedback_rates.get("accepted", 0.0) or 0.0),
            "corrected": float(feedback_rates.get("corrected", 0.0) or 0.0),
            "retried": float(feedback_rates.get("retried", 0.0) or 0.0),
            "ambiguous": float(feedback_rates.get("ambiguous", 0.0) or 0.0),
        },
        "top_correction_hints": top_correction_hints[:8],
        "recent_feedback": recent_feedback[:8],
        "repo_count": len(touched_repos),
        "touched_repos": touched_repos,
        "active_workdirs": active_workdirs[:8],
        "git_totals": {
            "repo_count": int(git_totals.get("repo_count", 0) or 0),
            "staged_files": int(git_totals.get("staged_files", 0) or 0),
            "modified_files": int(git_totals.get("modified_files", 0) or 0),
            "untracked_files": int(git_totals.get("untracked_files", 0) or 0),
            "commit_count": int(git_totals.get("commit_count", 0) or 0),
        },
        "evidence": evidence_payload,
        "usage": dict(usage or {}),
    }
    return snapshot


def append_timeseries_rows(path: str | Path, rows: Iterable[dict[str, Any]]) -> int:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict[str, Any]] = {}
    if target_path.exists():
        for row in _iter_jsonl(target_path):
            snapshot_id = str(row.get("snapshot_id", "")).strip()
            if snapshot_id:
                existing[snapshot_id] = row

    inserted = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        snapshot_id = str(row.get("snapshot_id", "")).strip()
        if not snapshot_id:
            continue
        if snapshot_id not in existing:
            inserted += 1
        existing[snapshot_id] = row

    ordered = sorted(existing.values(), key=lambda item: (str(item.get("ts", "")), str(item.get("snapshot_id", ""))))
    with target_path.open("w", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return inserted


def collect_codex_rollout_snapshots(
    *,
    start_date: str | date | datetime,
    end_date: str | date | datetime,
    sessions_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    root = Path(sessions_root or (Path.home() / ".codex" / "sessions")).expanduser().resolve()
    start_day = _coerce_date(start_date)
    end_day = _coerce_date(end_date)
    snapshots: list[dict[str, Any]] = []

    for day in _date_range(start_day, end_day):
        day_dir = root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        if not day_dir.exists():
            continue
        for rollout_file in sorted(day_dir.glob("rollout-*.jsonl")):
            try:
                snapshots.append(summarize_codex_rollout(rollout_file))
            except Exception:
                continue
    return snapshots


def summarize_period(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = [row for row in rows if isinstance(row, dict)]
    command_heads: Counter[str] = Counter()
    workdirs: Counter[str] = Counter()
    themes: Counter[str] = Counter()
    feedback_counts: Counter[str] = Counter()
    hint_counter: Counter[tuple[str, str]] = Counter()
    hint_examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_date: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sessions": 0,
            "user_prompts": 0,
            "exec_commands": 0,
            "duration_minutes": 0.0,
            "feedback_prompts": 0,
            "corrected": 0,
            "retried": 0,
            "accepted": 0,
        }
    )

    total_prompts = 0
    total_exec_commands = 0
    total_duration = 0.0
    total_feedback_prompts = 0

    for row in materialized:
        total_prompts += int(row.get("user_prompt_count", 0) or 0)
        total_exec_commands += int(row.get("exec_command_count", 0) or 0)
        total_duration += float(row.get("duration_minutes", 0.0) or 0.0)
        total_feedback_prompts += int(row.get("feedback_prompt_count", 0) or 0)
        for item in row.get("top_command_heads", []):
            if isinstance(item, dict):
                command_heads[str(item.get("command", ""))] += int(item.get("count", 0) or 0)
        for item in row.get("top_workdirs", []):
            if isinstance(item, dict):
                workdirs[str(item.get("workdir", ""))] += int(item.get("count", 0) or 0)
        for theme, count in (row.get("theme_counts", {}) or {}).items():
            themes[str(theme)] += int(count or 0)
        for outcome, count in (row.get("feedback_counts", {}) or {}).items():
            feedback_counts[str(outcome)] += int(count or 0)
        for item in row.get("top_correction_hints", []) or []:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category", "")).strip()
            label = str(item.get("label", "")).strip()
            count = int(item.get("count", 0) or 0)
            if not category or not label or count <= 0:
                continue
            key = (category, label)
            hint_counter[key] += count
            for example in item.get("examples", []) or []:
                text = str(example or "").strip()
                if text and len(hint_examples[key]) < 3 and text not in hint_examples[key]:
                    hint_examples[key].append(text)

        date_key = str(row.get("date", "")).strip()
        if date_key:
            by_date[date_key]["sessions"] += 1
            by_date[date_key]["user_prompts"] += int(row.get("user_prompt_count", 0) or 0)
            by_date[date_key]["exec_commands"] += int(row.get("exec_command_count", 0) or 0)
            by_date[date_key]["feedback_prompts"] += int(row.get("feedback_prompt_count", 0) or 0)
            daily_feedback = row.get("feedback_counts", {}) or {}
            by_date[date_key]["accepted"] += int(daily_feedback.get("accepted", 0) or 0)
            by_date[date_key]["corrected"] += int(daily_feedback.get("corrected", 0) or 0)
            by_date[date_key]["retried"] += int(daily_feedback.get("retried", 0) or 0)
            by_date[date_key]["duration_minutes"] = round(
                float(by_date[date_key]["duration_minutes"]) + float(row.get("duration_minutes", 0.0) or 0.0),
                1,
            )

    return {
        "session_count": len(materialized),
        "total_user_prompts": total_prompts,
        "total_exec_commands": total_exec_commands,
        "total_duration_minutes": round(total_duration, 1),
        "total_feedback_prompts": total_feedback_prompts,
        "feedback_totals": {
            "accepted": int(feedback_counts.get("accepted", 0) or 0),
            "corrected": int(feedback_counts.get("corrected", 0) or 0),
            "retried": int(feedback_counts.get("retried", 0) or 0),
            "ambiguous": int(feedback_counts.get("ambiguous", 0) or 0),
        },
        "feedback_rates": {
            "accepted": round((int(feedback_counts.get("accepted", 0) or 0) / total_feedback_prompts), 3)
            if total_feedback_prompts
            else 0.0,
            "corrected": round((int(feedback_counts.get("corrected", 0) or 0) / total_feedback_prompts), 3)
            if total_feedback_prompts
            else 0.0,
            "retried": round((int(feedback_counts.get("retried", 0) or 0) / total_feedback_prompts), 3)
            if total_feedback_prompts
            else 0.0,
            "ambiguous": round((int(feedback_counts.get("ambiguous", 0) or 0) / total_feedback_prompts), 3)
            if total_feedback_prompts
            else 0.0,
        },
        "top_correction_hints": [
            {
                "category": category,
                "label": label,
                "count": count,
                "examples": hint_examples.get((category, label), []),
            }
            for (category, label), count in hint_counter.most_common(8)
        ],
        "top_command_heads": _top_rows(command_heads, label="command"),
        "top_workdirs": _top_rows(workdirs, label="workdir"),
        "theme_totals": dict(themes),
        "daily": [
            {"date": date_key, **payload}
            for date_key, payload in sorted(by_date.items(), key=lambda item: item[0])
        ],
    }


def load_timeseries_rows(
    path: str | Path,
    *,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    kinds: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return []
    allowed_kinds = {str(item).strip() for item in (kinds or []) if str(item).strip()}
    start_day = _coerce_date(start_date) if start_date is not None and str(start_date) else None
    end_day = _coerce_date(end_date) if end_date is not None and str(end_date) else None

    rows: list[dict[str, Any]] = []
    for row in _iter_jsonl(target):
        kind = str(row.get("kind", "")).strip()
        if allowed_kinds and kind not in allowed_kinds:
            continue
        date_text = str(row.get("date", "")).strip()
        if not date_text:
            continue
        try:
            row_day = date.fromisoformat(date_text)
        except ValueError:
            continue
        if start_day is not None and row_day < start_day:
            continue
        if end_day is not None and row_day > end_day:
            continue
        rows.append(row)
    return rows


def _format_duration_minutes(minutes: float) -> str:
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    if hours <= 0:
        return f"{mins}m"
    return f"{hours}h {mins}m"


def _truncate_text(value: str, limit: int = 34) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def render_period_svg(
    rows: Iterable[dict[str, Any]],
    *,
    title: str,
    output_path: str | Path,
) -> dict[str, Any]:
    materialized = [row for row in rows if isinstance(row, dict)]
    summary = summarize_period(materialized)
    daily = summary.get("daily", [])
    if not daily:
        raise ValueError("시각화할 세션 데이터가 없습니다.")

    width = 1360
    height = 980
    margin_x = 72
    card_y = 96
    card_w = 272
    card_h = 92
    gap = 18

    def card(x: int, label: str, value: str, sub: str, accent: str) -> str:
        return (
            f'<rect x="{x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="18" fill="#ffffff" stroke="#d6dde8" />'
            f'<text x="{x + 20}" y="{card_y + 28}" font-size="14" fill="#5b6878">{escape(label)}</text>'
            f'<text x="{x + 20}" y="{card_y + 62}" font-size="34" font-weight="700" fill="{accent}">{escape(value)}</text>'
            f'<text x="{x + 20}" y="{card_y + 82}" font-size="13" fill="#7a8796">{escape(sub)}</text>'
        )

    cards_svg = "".join(
        [
            card(margin_x + (card_w + gap) * 0, "Sessions", str(summary["session_count"]), "captured sessions", "#0f172a"),
            card(margin_x + (card_w + gap) * 1, "Prompts", str(summary["total_user_prompts"]), "user prompts", "#0f766e"),
            card(margin_x + (card_w + gap) * 2, "Exec Commands", str(summary["total_exec_commands"]), "terminal exploration load", "#92400e"),
            card(
                margin_x + (card_w + gap) * 3,
                "Tracked Time",
                _format_duration_minutes(float(summary["total_duration_minutes"])),
                "session span",
                "#7c3aed",
            ),
        ]
    )

    prompts_max = max(int(item.get("user_prompts", 0) or 0) for item in daily) or 1
    exec_max = max(int(item.get("exec_commands", 0) or 0) for item in daily) or 1
    top_theme_pairs = sorted((summary.get("theme_totals", {}) or {}).items(), key=lambda item: item[1], reverse=True)[:6]
    top_theme_max = max((int(count) for _, count in top_theme_pairs), default=1)
    top_workdirs = summary.get("top_workdirs", [])[:3]

    bar_area_x = margin_x
    bar_area_w = width - (margin_x * 2)
    bar_group_w = bar_area_w / max(1, len(daily))
    bar_w = min(72, bar_group_w * 0.42)
    prompt_chart_y = 250
    prompt_chart_h = 220
    exec_chart_y = 550
    exec_chart_h = 220

    def build_daily_bars(chart_y: int, chart_h: int, key: str, color: str, max_value: int) -> str:
        parts = [
            f'<rect x="{bar_area_x}" y="{chart_y}" width="{bar_area_w}" height="{chart_h}" rx="18" fill="#ffffff" stroke="#d6dde8" />'
        ]
        for idx, item in enumerate(daily):
            value = int(item.get(key, 0) or 0)
            date_label = str(item.get("date", ""))[5:]
            x = bar_area_x + (idx * bar_group_w) + (bar_group_w - bar_w) / 2
            height_ratio = value / max_value if max_value else 0
            filled_h = max(2.0, (chart_h - 58) * height_ratio)
            y = chart_y + chart_h - 34 - filled_h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{filled_h:.1f}" rx="12" fill="{color}" opacity="0.88" />')
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-size="14" fill="#334155">{value}</text>'
            )
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{chart_y + chart_h - 10}" text-anchor="middle" font-size="13" fill="#64748b">{escape(date_label)}</text>'
            )
        return "".join(parts)

    prompt_chart_svg = build_daily_bars(prompt_chart_y, prompt_chart_h, "user_prompts", "#0f766e", prompts_max)
    exec_chart_svg = build_daily_bars(exec_chart_y, exec_chart_h, "exec_commands", "#c2410c", exec_max)

    theme_chart_x = margin_x
    theme_chart_y = 820
    theme_chart_w = 820
    theme_chart_h = 118
    theme_bar_max_w = 520
    theme_parts = [f'<rect x="{theme_chart_x}" y="{theme_chart_y}" width="{theme_chart_w}" height="{theme_chart_h}" rx="18" fill="#ffffff" stroke="#d6dde8" />']
    for idx, (theme, count) in enumerate(top_theme_pairs):
        row_y = theme_chart_y + 28 + (idx * 16)
        bar_w_px = (int(count) / top_theme_max) * theme_bar_max_w if top_theme_max else 0
        theme_parts.append(f'<text x="{theme_chart_x + 18}" y="{row_y}" font-size="13" fill="#334155">{escape(theme)}</text>')
        theme_parts.append(
            f'<rect x="{theme_chart_x + 150}" y="{row_y - 10}" width="{bar_w_px:.1f}" height="10" rx="5" fill="#3b82f6" opacity="0.84" />'
        )
        theme_parts.append(f'<text x="{theme_chart_x + 680}" y="{row_y}" font-size="13" fill="#475569">{int(count)}</text>')
    theme_chart_svg = "".join(theme_parts)

    side_x = 930
    side_y = 820
    side_w = width - side_x - margin_x
    side_h = 118
    side_parts = [f'<rect x="{side_x}" y="{side_y}" width="{side_w}" height="{side_h}" rx="18" fill="#ffffff" stroke="#d6dde8" />']
    side_parts.append(f'<text x="{side_x + 18}" y="{side_y + 28}" font-size="14" fill="#5b6878">Top workdirs</text>')
    for idx, item in enumerate(top_workdirs):
        label = _truncate_text(str(item.get("workdir", "")).replace("/Users/boram/", ""), 36)
        count = int(item.get("count", 0) or 0)
        side_parts.append(
            f'<text x="{side_x + 18}" y="{side_y + 54 + (idx * 20)}" font-size="13" fill="#0f172a">{idx + 1}. {escape(label)} ({count})</text>'
        )
    side_svg = "".join(side_parts)

    top_commands = ", ".join(f"{item['command']} {item['count']}" for item in summary.get("top_command_heads", [])[:4])
    subtitle = (
        f"{daily[0]['date']} to {daily[-1]['date']}  |  prompts {summary['total_user_prompts']}  |  "
        f"exec {summary['total_exec_commands']}  |  top cmds {top_commands}"
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <rect width="100%" height="100%" fill="#f8fafc" />
  <text x="{margin_x}" y="54" font-size="30" font-weight="700" fill="#0f172a">{escape(title)}</text>
  <text x="{margin_x}" y="78" font-size="14" fill="#64748b">{escape(subtitle)}</text>
  {cards_svg}
  <text x="{margin_x}" y="{prompt_chart_y - 18}" font-size="18" font-weight="600" fill="#0f172a">Daily prompts</text>
  {prompt_chart_svg}
  <text x="{margin_x}" y="{exec_chart_y - 18}" font-size="18" font-weight="600" fill="#0f172a">Daily exec commands</text>
  {exec_chart_svg}
  <text x="{margin_x}" y="{theme_chart_y - 18}" font-size="18" font-weight="600" fill="#0f172a">Theme totals</text>
  {theme_chart_svg}
  {side_svg}
</svg>"""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svg, encoding="utf-8")
    return {
        "status": "success",
        "output_file": str(target.resolve()),
        "summary": summary,
        "title": title,
    }


def backfill_codex_sessions(
    *,
    workdir: str | Path,
    start_date: str | date | datetime,
    end_date: str | date | datetime,
    output_file: str = "logs/session_timeseries.jsonl",
    sessions_root: str | Path | None = None,
) -> dict[str, Any]:
    snapshots = collect_codex_rollout_snapshots(
        start_date=start_date,
        end_date=end_date,
        sessions_root=sessions_root,
    )
    target = Path(workdir).resolve() / output_file
    inserted = append_timeseries_rows(target, snapshots)
    return {
        "status": "success",
        "output_file": str(target),
        "inserted": inserted,
        "snapshot_count": len(snapshots),
        "summary": summarize_period(snapshots),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and persist Codex/BoramClaw session time-series snapshots.")
    parser.add_argument("--backfill-codex", action="store_true", help="Backfill Codex rollout sessions into a BoramClaw JSONL store.")
    parser.add_argument("--render-svg", action="store_true", help="Render a static SVG dashboard from session_timeseries.jsonl.")
    parser.add_argument("--start-date", default="", help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", default="", help="Inclusive end date (YYYY-MM-DD).")
    parser.add_argument("--workdir", default=".", help="BoramClaw workdir used for output.")
    parser.add_argument("--sessions-root", default="", help="Override Codex sessions root.")
    parser.add_argument("--output-file", default="logs/session_timeseries.jsonl", help="JSONL file to write snapshots into.")
    parser.add_argument("--input-file", default="logs/session_timeseries.jsonl", help="JSONL file used as visualization input.")
    parser.add_argument("--svg-output", default="logs/reviews/session_timeseries.svg", help="SVG output path.")
    parser.add_argument("--title", default="Session Time-Series Review", help="SVG title.")
    parser.add_argument("--kinds", default="", help="Comma-separated kinds filter, e.g. codex_rollout,wrapup")
    args = parser.parse_args()

    if args.backfill_codex:
        if not args.start_date or not args.end_date:
            raise SystemExit("--backfill-codex requires --start-date and --end-date")
        result = backfill_codex_sessions(
            workdir=args.workdir,
            start_date=args.start_date,
            end_date=args.end_date,
            output_file=args.output_file,
            sessions_root=(args.sessions_root or None),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.render_svg:
        rows = load_timeseries_rows(
            Path(args.workdir).resolve() / args.input_file,
            start_date=(args.start_date or None),
            end_date=(args.end_date or None),
            kinds=[item.strip() for item in args.kinds.split(",") if item.strip()],
        )
        result = render_period_svg(
            rows,
            title=args.title,
            output_path=(Path(args.workdir).resolve() / args.svg_output),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit("No action selected. Use --backfill-codex or --render-svg.")


if __name__ == "__main__":
    raise SystemExit(main())
