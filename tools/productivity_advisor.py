from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from workday_recap import run as workday_run

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "productivity_advisor",
    "description": "최근 N일간 활동 패턴을 분석하여 개인화된 생산성 최적화 제안을 생성합니다.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "days_back": {
                "type": "integer",
                "default": 7,
                "description": "분석할 기간 (일)",
            },
            "output_format": {
                "type": "string",
                "enum": ["text", "json"],
                "default": "text",
            },
        },
        "required": [],
    },
}


def _severity_for(category: str) -> str:
    if category in {"late_night", "context_switch"}:
        return "warning"
    if category in {"commit_frequency", "day_pattern"}:
        return "suggestion"
    return "info"


def _add_insight(
    insights: list[dict[str, Any]],
    category: str,
    title: str,
    description: str,
    recommendation: str,
) -> None:
    insights.append(
        {
            "category": category,
            "severity": _severity_for(category),
            "title": title,
            "description": description,
            "recommendation": recommendation,
        }
    )


def _format_hour_block(start: str, end: str) -> str:
    try:
        s = int(start)
        e = int(end)
    except ValueError:
        return f"{start}-{end}시"
    if s < 12:
        return f"오전 {s}-{e}시"
    if s == 12:
        return f"오후 12-{e}시"
    return f"오후 {s}-{e}시"


def _analyze_insights(report: dict[str, Any], days_back: int) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    sections = report.get("sections", {})
    timeline = report.get("timeline", {})
    productivity = report.get("productivity_analysis", {})

    # A. 피크 생산성 시간대
    peak_block = productivity.get("peak_block", {})
    peak_total = int(peak_block.get("total", 0) or 0)
    peak_start = str(peak_block.get("start", ""))
    peak_end = str(peak_block.get("end", ""))
    if peak_total > 0 and peak_start:
        block_text = _format_hour_block(peak_start, peak_end)
        _add_insight(
            insights,
            "peak_time",
            "피크 집중 시간",
            f"{block_text} 활동이 가장 높습니다.",
            "중요 작업을 이 시간대에 배치해 보세요.",
        )

    # B. 야근 패턴
    hourly = timeline.get("hourly", {})
    total_activity = 0
    late_night_activity = 0
    for hour in range(24):
        row = hourly.get(hour, {}) if isinstance(hourly, dict) else {}
        total = int(row.get("total", 0) or 0)
        total_activity += total
        if hour >= 22:
            late_night_activity += total
    late_ratio = (late_night_activity / total_activity) if total_activity > 0 else 0.0
    if total_activity > 0 and late_ratio >= 0.2:
        _add_insight(
            insights,
            "late_night",
            "야간 작업 비중 높음",
            f"지난 {days_back}일간 22시 이후 작업 비율이 {round(late_ratio * 100, 1)}%입니다.",
            "다음 주 오전 집중 블록을 늘려 수면 리듬을 안정화해 보세요.",
        )

    # C. Context switching 과다
    context_switches = int(productivity.get("context_switches", 0) or 0)
    daily_switches = context_switches / max(days_back, 1)
    if daily_switches > 5:
        _add_insight(
            insights,
            "context_switch",
            "작업 전환 과다",
            f"하루 평균 {round(daily_switches, 1)}번의 작업 전환이 감지됩니다.",
            "25분 집중 블록(포모도로)과 작업 큐 단일화를 권장합니다.",
        )

    # D. 커밋 없는 긴 작업
    git_section = sections.get("git", {})
    shell_section = sections.get("shell", {})
    commit_count = int(git_section.get("total_commits", 0) or 0)
    shell_commands = int(shell_section.get("total_commands", 0) or 0)
    if commit_count < 3 and shell_commands >= 200:
        _add_insight(
            insights,
            "commit_frequency",
            "코딩 대비 커밋 빈도 낮음",
            f"코딩 명령어 활동({shell_commands}회) 대비 커밋 수({commit_count}개)가 낮습니다.",
            "작업 단위를 더 작게 나누고 중간 커밋을 늘려 보세요.",
        )

    # E. 특정 요일 패턴
    commits = git_section.get("commits", [])
    weekday_counts: dict[str, int] = {}
    for commit in commits if isinstance(commits, list) else []:
        date_text = str(commit.get("date", ""))
        try:
            dt = datetime.fromisoformat(date_text)
        except ValueError:
            continue
        weekday = dt.strftime("%A")
        weekday_counts[weekday] = weekday_counts.get(weekday, 0) + 1
    if len(weekday_counts) >= 3:
        min_day = min(weekday_counts, key=weekday_counts.get)
        min_count = weekday_counts[min_day]
        others = [v for k, v in weekday_counts.items() if k != min_day]
        avg_others = (sum(others) / len(others)) if others else 0
        if avg_others > 0 and min_count <= avg_others * 0.6:
            drop_pct = round((1 - (min_count / avg_others)) * 100, 1)
            _add_insight(
                insights,
                "day_pattern",
                "요일별 편차 감지",
                f"{min_day} 활동량이 다른 요일 평균 대비 {drop_pct}% 낮습니다.",
                f"{min_day} 오전 루틴(계획 10분 + 첫 집중 블록)을 고정해 보세요.",
            )

    if not insights:
        _add_insight(
            insights,
            "peak_time",
            "안정적 패턴",
            "최근 데이터에서 뚜렷한 위험 신호는 감지되지 않았습니다.",
            "현재 리듬을 유지하되 주 1회 회고로 미세 조정해 보세요.",
        )

    return insights


def _build_summary(insights: list[dict[str, Any]]) -> str:
    warning_count = sum(1 for item in insights if item.get("severity") == "warning")
    if warning_count >= 2:
        return "리듬 불안정 신호가 있어 다음 주 집중 시간 재설계가 필요합니다."
    if warning_count == 1:
        return "핵심 개선 포인트 1개가 감지되었습니다. 이번 주 실험으로 교정해보세요."
    return "전반적으로 안정적인 생산성 패턴입니다."


def _to_text(period: str, insights: list[dict[str, Any]], summary: str) -> str:
    lines = [f"📊 생산성 리포트 ({period})", ""]
    title_map = {
        "peak_time": "💡 피크 시간",
        "late_night": "⚠️ 야근 패턴",
        "context_switch": "⚠️ 컨텍스트 전환",
        "commit_frequency": "💾 커밋 패턴",
        "day_pattern": "📅 요일 패턴",
    }
    for insight in insights:
        category = str(insight.get("category", "peak_time"))
        lines.append(f"[{title_map.get(category, '💡 인사이트')}]")
        lines.append(str(insight.get("description", "")))
        lines.append(f"→ {insight.get('recommendation', '')}")
        lines.append("")
    lines.append(f"요약: {summary}")
    return "\n".join(lines).strip()


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    days_back = int(input_data.get("days_back", 7) or 7)
    output_format = str(input_data.get("output_format", "text")).strip().lower() or "text"

    recap_result = workday_run({"mode": "weekly", "scan_all_repos": False}, context)
    report = recap_result.get("report", {}) if isinstance(recap_result, dict) else {}

    insights = _analyze_insights(report, days_back=days_back)
    period = f"최근 {days_back}일"
    summary = _build_summary(insights)

    result = {
        "ok": True,
        "period": period,
        "insights": insights,
        "summary": summary,
    }

    if output_format == "text":
        result["text"] = _to_text(period, insights, summary)
    return result


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


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
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
