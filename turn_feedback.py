from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable


OUTCOMES = ("accepted", "corrected", "retried", "ambiguous")

_CORRECTION_PATTERNS = (
    "아니",
    "틀렸",
    "잘못",
    "너무 짧",
    "부족",
    "고쳐",
    "수정",
    "바꿔",
    "말고",
    "존댓말",
    "존대말",
    "더 길",
    "길게",
    "자세",
    "상세",
    "구체",
    "깊게",
    "프롬프트 분석",
    "프롬프트를 확인",
    "프롬프트도",
    "실제로 구현",
    "깃도",
    "git도",
    "로컬 폴더",
    "어제 기준",
    "오늘 실제",
    "월요일부터",
    "openclaw처럼",
    "openclaw 식",
    "openclaw식",
)

_RETRY_PATTERNS = (
    "다시",
    "이어",
    "진행해",
    "띄워봐",
    "열어봐",
    "생성해놔",
    "돌려",
    "재실행",
    "계속",
    "한 번 더",
)

_ACCEPT_PATTERNS = (
    "좋다",
    "좋아요",
    "좋네요",
    "좋군",
    "훌륭",
    "너무 좋",
    "아주 좋",
    "great",
    "nice",
    "excellent",
)

_LEADING_FEEDBACK_PATTERNS = (
    "아니",
    "다시",
    "이어",
    "존댓말",
    "존대말",
    "어제 기준",
    "오늘 실제",
    "실제로 구현",
    "좋다",
    "좋아요",
    "좋네요",
    "좋군",
    "훌륭",
    "너무 좋",
)

_HINT_RULES = (
    {
        "category": "tone_honorific",
        "label": "존댓말 유지",
        "patterns": ("존댓말", "존대말", "존대"),
    },
    {
        "category": "depth_expand",
        "label": "더 길고 자세한 설명",
        "patterns": ("너무 짧", "더 길", "길게", "자세", "상세", "구체", "깊게"),
    },
    {
        "category": "evidence_first",
        "label": "Git/로컬 근거 우선",
        "patterns": ("실제로 구현", "실제로", "깃도", "git도", "git ", "로컬 폴더", "근거", "증거"),
    },
    {
        "category": "prompt_analysis",
        "label": "프롬프트 흐름 분석 포함",
        "patterns": ("프롬프트 분석", "프롬프트를 확인", "프롬프트도", "프롬프트 흐름"),
    },
    {
        "category": "date_scope",
        "label": "어제/오늘/주간 기준 명시",
        "patterns": ("어제 기준", "오늘 실제", "오늘 기준", "이번주", "월요일부터", "기준으로"),
    },
    {
        "category": "openclaw_style",
        "label": "OpenClaw 스타일 반영",
        "patterns": ("openclaw처럼", "openclaw 식", "openclaw식"),
    },
)


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _has_any(text: str, patterns: Iterable[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _extract_hint_matches(text: str) -> list[dict[str, str]]:
    lowered = _normalize(text)
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for rule in _HINT_RULES:
        if _has_any(lowered, rule["patterns"]):
            category = str(rule["category"])
            if category in seen:
                continue
            seen.add(category)
            matches.append(
                {
                    "category": category,
                    "label": str(rule["label"]),
                }
            )
    return matches


def classify_feedback_text(text: str) -> dict[str, Any]:
    lowered = _normalize(text)
    hints = _extract_hint_matches(lowered)

    if _has_any(lowered, _CORRECTION_PATTERNS):
        outcome = "corrected"
    elif _has_any(lowered, _ACCEPT_PATTERNS) and "다시" not in lowered and "재실행" not in lowered:
        outcome = "accepted"
    elif _has_any(lowered, _RETRY_PATTERNS):
        outcome = "retried"
    else:
        outcome = "ambiguous"

    return {
        "outcome": outcome,
        "hints": hints,
    }


def _parse_ts(raw: Any) -> tuple[int, str]:
    text = str(raw or "").strip()
    if not text:
        return (1, "")
    normalized = text.replace("Z", "+00:00")
    try:
        return (0, datetime.fromisoformat(normalized).isoformat())
    except ValueError:
        return (1, text)


def summarize_turn_feedback(
    prompt_rows: list[dict[str, Any]],
    *,
    recent_limit: int = 8,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(prompt_rows):
        if not isinstance(row, dict):
            continue
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        session_id = str(row.get("session_id", "")).strip() or "__global__"
        grouped[session_id].append({"index": index, **row})

    outcome_counts: Counter[str] = Counter({name: 0 for name in OUTCOMES})
    hint_counter: Counter[tuple[str, str]] = Counter()
    hint_examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    feedback_events: list[dict[str, Any]] = []

    for session_id, rows in grouped.items():
        ordered = sorted(
            rows,
            key=lambda item: (_parse_ts(item.get("ts"))[0], _parse_ts(item.get("ts"))[1], int(item.get("index", 0) or 0)),
        )
        for position, row in enumerate(ordered):
            text = str(row.get("text", "")).strip()
            lowered = _normalize(text)
            classified = classify_feedback_text(text)
            outcome = str(classified.get("outcome", "ambiguous"))
            is_candidate = position > 0 or _has_any(lowered, _LEADING_FEEDBACK_PATTERNS)
            if not is_candidate:
                continue

            outcome_counts[outcome] += 1
            hint_labels = [str(item.get("label", "")).strip() for item in classified.get("hints", []) if isinstance(item, dict)]
            hint_categories = [
                str(item.get("category", "")).strip() for item in classified.get("hints", []) if isinstance(item, dict)
            ]

            if outcome == "corrected":
                for item in classified.get("hints", []):
                    if not isinstance(item, dict):
                        continue
                    category = str(item.get("category", "")).strip()
                    label = str(item.get("label", "")).strip()
                    if not category or not label:
                        continue
                    key = (category, label)
                    hint_counter[key] += 1
                    if len(hint_examples[key]) < 3 and text not in hint_examples[key]:
                        hint_examples[key].append(text[:220])

            feedback_events.append(
                {
                    "session_id": "" if session_id == "__global__" else session_id,
                    "ts": str(row.get("ts", "")).strip(),
                    "outcome": outcome,
                    "text": text[:220],
                    "hint_labels": hint_labels,
                    "hint_categories": hint_categories,
                }
            )

    feedback_prompt_count = sum(outcome_counts.values())
    top_correction_hints = [
        {
            "category": category,
            "label": label,
            "count": count,
            "examples": hint_examples.get((category, label), []),
        }
        for (category, label), count in hint_counter.most_common(8)
    ]

    recent_feedback = sorted(
        feedback_events,
        key=lambda item: (_parse_ts(item.get("ts"))[0], _parse_ts(item.get("ts"))[1], str(item.get("text", ""))),
    )[-recent_limit:]

    return {
        "feedback_prompt_count": feedback_prompt_count,
        "feedback_counts": {
            outcome: int(outcome_counts.get(outcome, 0) or 0)
            for outcome in OUTCOMES
        },
        "feedback_rates": {
            outcome: round((int(outcome_counts.get(outcome, 0) or 0) / feedback_prompt_count), 3) if feedback_prompt_count else 0.0
            for outcome in OUTCOMES
        },
        "top_correction_hints": top_correction_hints,
        "recent_feedback": recent_feedback,
    }
