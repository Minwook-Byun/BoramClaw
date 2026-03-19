#!/usr/bin/env python3
"""
Weekly Goal Manager - Meta Impact 원칙 기반 주간 목표 선언 & 추적

Meta의 핵심 원칙:
1. Activity vs Impact 구분 - "열심히 했다" ≠ "임팩트를 냈다"
2. 문서화된 기대치 - 자율의 대가는 명확한 기대치 문서화
3. No Surprise - 기대치 갭이 발견되면 즉시 알림

사용법:
- 월요일: declare_goals로 주간 Impact 목표 선언
- 매일: check_progress로 진척도 확인
- 금요일: evaluate_week로 주간 임팩트 평가
"""

import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "weekly_goal_manager",
    "description": """Meta Impact 원칙 기반 주간 목표 관리.

    사용 시나리오:
    - "이번 주 목표 설정해줘" → action="declare"
    - "목표 진척도 확인" → action="check"
    - "주간 임팩트 평가" → action="evaluate"
    - "목표 갱신" → action="update"

    Meta 원칙: Activity(과정) vs Impact(결과) 구분으로
    '열심히 했다'가 아닌 '의미있는 결과'를 추적합니다.""",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["declare", "check", "update", "evaluate"],
                "description": "declare=목표 선언, check=진척도 확인, update=목표 갱신, evaluate=주간 평가",
            },
            "goals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "success_criteria": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["impact", "investment", "activity"],
                        },
                    },
                },
                "description": "declare 시 목표 리스트",
            },
            "goal_index": {
                "type": "integer",
                "description": "update 시 갱신할 목표 인덱스 (0-based)",
            },
            "progress_note": {
                "type": "string",
                "description": "update 시 진척 노트",
            },
            "status": {
                "type": "string",
                "enum": ["not_started", "in_progress", "completed", "blocked", "dropped"],
                "description": "update 시 목표 상태",
            },
        },
        "required": ["action"],
    },
}

GOALS_DIR = Path("config")
GOALS_FILE = GOALS_DIR / "weekly_goals.json"


def _current_week_key() -> str:
    """현재 주 키 (YYYY-WNN)"""
    now = datetime.now()
    return f"{now.year}-W{now.strftime('%W')}"


def _load_goals() -> Dict[str, Any]:
    """주간 목표 파일 로드"""
    if GOALS_FILE.exists():
        try:
            return json.loads(GOALS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"weeks": {}}


def _save_goals(data: Dict[str, Any]) -> None:
    """주간 목표 파일 저장"""
    GOALS_DIR.mkdir(parents=True, exist_ok=True)
    GOALS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _classify_commit(message: str) -> str:
    """커밋 메시지를 Impact/Investment/Activity로 분류"""
    msg = message.lower()

    # Impact: 직접적인 비즈니스/프로젝트 가치 창출
    impact_signals = [
        "feat:", "feature:", "fix:", "perf:",
        "구현", "완성", "배포", "릴리스", "해결",
        "추가", "개선", "최적화", "v1.", "v2.", "v3.",
        "✨", "🐛", "⚡", "🚀",
    ]
    if any(sig in msg for sig in impact_signals):
        return "impact"

    # Investment: 미래 임팩트를 위한 투자
    investment_signals = [
        "test:", "infra:", "ci:", "cd:",
        "테스트", "실험", "프로토", "poc", "학습",
        "인프라", "설정", "환경", "모니터링",
        "🧪", "🔧", "📦",
    ]
    if any(sig in msg for sig in investment_signals):
        return "investment"

    # Activity: 필요하지만 직접적 임팩트는 아닌 것
    return "activity"


def _get_week_commits(workdir: str = ".") -> List[Dict[str, Any]]:
    """이번 주 커밋 수집 및 분류"""
    commits = []
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--pretty=format:%H|%ad|%s", "--date=iso"],
            cwd=workdir, capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                msg = parts[2]
                commits.append({
                    "hash": parts[0][:7],
                    "date": parts[1][:10],
                    "message": msg,
                    "impact_type": _classify_commit(msg),
                })
    except Exception:
        pass

    return commits


def _compute_impact_score(commits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Impact Score 계산"""
    if not commits:
        return {
            "total_commits": 0,
            "impact_commits": 0,
            "investment_commits": 0,
            "activity_commits": 0,
            "impact_density": 0.0,
            "investment_ratio": 0.0,
            "impact_score": 0.0,
            "grade": "N/A",
        }

    impact = sum(1 for c in commits if c["impact_type"] == "impact")
    investment = sum(1 for c in commits if c["impact_type"] == "investment")
    activity = sum(1 for c in commits if c["impact_type"] == "activity")
    total = len(commits)

    impact_density = impact / total
    investment_ratio = investment / total

    # Impact Score: 70% 임팩트 밀도 + 30% 투자 비율
    score = (impact_density * 70) + (investment_ratio * 30)

    # Grade
    if score >= 60:
        grade = "A (High Impact)"
    elif score >= 40:
        grade = "B (Moderate Impact)"
    elif score >= 20:
        grade = "C (Low Impact)"
    else:
        grade = "D (Activity-Heavy)"

    return {
        "total_commits": total,
        "impact_commits": impact,
        "investment_commits": investment,
        "activity_commits": activity,
        "impact_density": round(impact_density, 3),
        "investment_ratio": round(investment_ratio, 3),
        "impact_score": round(score, 1),
        "grade": grade,
    }


def declare_goals(goals_input: List[Dict[str, Any]]) -> Dict[str, Any]:
    """주간 Impact 목표 선언"""
    week_key = _current_week_key()
    data = _load_goals()

    goals = []
    for g in goals_input:
        goals.append({
            "description": g.get("description", ""),
            "success_criteria": g.get("success_criteria", ""),
            "category": g.get("category", "impact"),
            "status": "not_started",
            "declared_at": datetime.now().isoformat(),
            "progress_notes": [],
        })

    data["weeks"][week_key] = {
        "declared_at": datetime.now().isoformat(),
        "goals": goals,
        "midweek_check": None,
        "final_evaluation": None,
    }

    _save_goals(data)

    return {
        "success": True,
        "week": week_key,
        "goals_count": len(goals),
        "impact_goals": sum(1 for g in goals if g["category"] == "impact"),
        "investment_goals": sum(1 for g in goals if g["category"] == "investment"),
        "message": f"{week_key} 주간 목표 {len(goals)}개 선언 완료. Meta 원칙: 금요일에 임팩트로 평가됩니다.",
    }


def check_progress(workdir: str = ".") -> Dict[str, Any]:
    """No Surprise 진척도 체크"""
    week_key = _current_week_key()
    data = _load_goals()
    week_data = data.get("weeks", {}).get(week_key)

    if not week_data:
        return {
            "success": False,
            "message": f"{week_key} 주간 목표가 없습니다. 먼저 목표를 선언하세요.",
            "has_goals": False,
        }

    goals = week_data.get("goals", [])
    commits = _get_week_commits(workdir)
    impact_score = _compute_impact_score(commits)

    # 목표별 상태 분석
    not_started = [g for g in goals if g["status"] == "not_started"]
    in_progress = [g for g in goals if g["status"] == "in_progress"]
    completed = [g for g in goals if g["status"] == "completed"]
    blocked = [g for g in goals if g["status"] == "blocked"]

    # No Surprise 갭 알림
    alerts = []
    now = datetime.now()
    declared = datetime.fromisoformat(week_data["declared_at"])
    days_elapsed = (now - declared).days

    if days_elapsed >= 3 and not_started:
        for g in not_started:
            alerts.append({
                "type": "no_surprise_gap",
                "severity": "high",
                "message": f"⚠️ 수요일인데 아직 시작도 안 됨: \"{g['description']}\"",
            })

    if days_elapsed >= 4 and len(completed) < len(goals) * 0.5:
        alerts.append({
            "type": "midweek_impact_low",
            "severity": "medium",
            "message": f"⚠️ 목요일인데 완료율 {len(completed)}/{len(goals)}. 금요일까지 가능한가?",
        })

    if impact_score["impact_density"] < 0.2 and impact_score["total_commits"] > 3:
        alerts.append({
            "type": "activity_heavy",
            "severity": "medium",
            "message": f"⚠️ 커밋 {impact_score['total_commits']}개 중 Impact 커밋이 {impact_score['impact_commits']}개뿐. Activity 위주의 작업 패턴.",
        })

    # 중간 체크 저장
    week_data["midweek_check"] = {
        "checked_at": now.isoformat(),
        "days_elapsed": days_elapsed,
        "alerts": alerts,
    }
    _save_goals(data)

    return {
        "success": True,
        "week": week_key,
        "days_elapsed": days_elapsed,
        "goal_status": {
            "total": len(goals),
            "not_started": len(not_started),
            "in_progress": len(in_progress),
            "completed": len(completed),
            "blocked": len(blocked),
        },
        "goals": [
            {
                "index": i,
                "description": g["description"],
                "category": g["category"],
                "status": g["status"],
                "success_criteria": g["success_criteria"],
                "progress_notes": g.get("progress_notes", [])[-3:],
            }
            for i, g in enumerate(goals)
        ],
        "impact_score": impact_score,
        "no_surprise_alerts": alerts,
        "commits_classified": [
            {"message": c["message"], "type": c["impact_type"]}
            for c in commits[:10]
        ],
    }


def update_goal(goal_index: int, status: Optional[str], progress_note: Optional[str]) -> Dict[str, Any]:
    """목표 상태 업데이트"""
    week_key = _current_week_key()
    data = _load_goals()
    week_data = data.get("weeks", {}).get(week_key)

    if not week_data:
        return {"success": False, "message": "이번 주 목표가 없습니다."}

    goals = week_data.get("goals", [])
    if goal_index < 0 or goal_index >= len(goals):
        return {"success": False, "message": f"유효하지 않은 인덱스: {goal_index}"}

    goal = goals[goal_index]
    if status:
        goal["status"] = status
    if progress_note:
        goal.setdefault("progress_notes", []).append({
            "note": progress_note,
            "timestamp": datetime.now().isoformat(),
        })

    _save_goals(data)
    return {
        "success": True,
        "updated_goal": goal["description"],
        "new_status": goal["status"],
    }


def evaluate_week(workdir: str = ".") -> Dict[str, Any]:
    """주간 Impact 최종 평가 (금요일)"""
    week_key = _current_week_key()
    data = _load_goals()
    week_data = data.get("weeks", {}).get(week_key)

    commits = _get_week_commits(workdir)
    impact_score = _compute_impact_score(commits)

    evaluation = {
        "week": week_key,
        "evaluated_at": datetime.now().isoformat(),
        "impact_score": impact_score,
        "commits_by_type": {
            "impact": [c for c in commits if c["impact_type"] == "impact"],
            "investment": [c for c in commits if c["impact_type"] == "investment"],
            "activity": [c for c in commits if c["impact_type"] == "activity"],
        },
    }

    if week_data:
        goals = week_data.get("goals", [])
        completed = [g for g in goals if g["status"] == "completed"]
        evaluation["goal_completion"] = {
            "total": len(goals),
            "completed": len(completed),
            "completion_rate": round(len(completed) / max(len(goals), 1), 3),
            "goals_detail": goals,
        }

        # Meta 자기 피드백: 솔직한 평가
        evaluation["meta_feedback"] = _generate_meta_feedback(
            goals, commits, impact_score
        )

        # 최종 평가 저장
        week_data["final_evaluation"] = evaluation
        _save_goals(data)
    else:
        evaluation["goal_completion"] = None
        evaluation["meta_feedback"] = {
            "verdict": "목표 미선언",
            "message": "이번 주는 목표를 선언하지 않았습니다. Meta 원칙: 기대치 없이는 평가도 없다.",
        }

    return {"success": True, "evaluation": evaluation}


def _generate_meta_feedback(
    goals: List[Dict], commits: List[Dict], impact_score: Dict
) -> Dict[str, Any]:
    """Meta 원칙 기반 솔직한 자기 피드백"""
    completed = [g for g in goals if g["status"] == "completed"]
    completion_rate = len(completed) / max(len(goals), 1)

    feedback = {
        "completion_rate": round(completion_rate, 3),
        "impact_grade": impact_score.get("grade", "N/A"),
    }

    # Verdict
    if completion_rate >= 0.8 and impact_score.get("impact_score", 0) >= 50:
        feedback["verdict"] = "🔥 고성과 주간"
        feedback["message"] = (
            "목표 달성률과 Impact 모두 높은 주간. "
            "Meta 기준: 이런 주가 3주 연속이면 레벨업 시그널."
        )
    elif completion_rate >= 0.5:
        feedback["verdict"] = "⚡ 적정 수준"
        feedback["message"] = (
            f"목표 {len(completed)}/{len(goals)} 완료. "
            f"Impact Score {impact_score.get('impact_score', 0):.1f}. "
            "Meta 기준: 안정적이지만 성장 여지가 있다."
        )
    elif impact_score.get("impact_score", 0) >= 40:
        feedback["verdict"] = "📊 Activity 과다"
        feedback["message"] = (
            "열심히 했지만 선언한 목표 달성률이 낮다. "
            "Meta 원칙: '열심히 했다'는 피드백의 독소 조항. "
            "다음 주: 목표를 줄이고 임팩트에 집중."
        )
    else:
        feedback["verdict"] = "🪞 정직한 회고 필요"
        feedback["message"] = (
            f"목표 달성률 {completion_rate:.0%}, Impact Score {impact_score.get('impact_score', 0):.1f}. "
            "Meta 원칙: No Surprise — 이 결과가 놀랍다면 매니저(=나 자신)의 관리 실패. "
            "다음 주: 목표 2개 이내, 매일 진척 체크."
        )

    # 자기 채찍질 포인트
    whip_points = []
    if impact_score.get("activity_commits", 0) > impact_score.get("impact_commits", 0) * 2:
        whip_points.append(
            f"Activity 커밋({impact_score['activity_commits']}개)이 Impact 커밋({impact_score['impact_commits']}개)의 2배 이상. "
            "바쁘게 '일한 것'과 '성과를 낸 것'은 다르다."
        )
    not_started = [g for g in goals if g["status"] == "not_started"]
    if not_started:
        whip_points.append(
            f"시작조차 안 한 목표 {len(not_started)}개. "
            "선언만 하고 실행하지 않는 건 자기기만이다."
        )
    dropped = [g for g in goals if g["status"] == "dropped"]
    if dropped:
        whip_points.append(
            f"포기한 목표 {len(dropped)}개. 포기 자체는 OK지만 — 왜 포기했는지 기록했는가?"
        )
    if not whip_points:
        whip_points.append("이번 주는 선방. 다음 주 목표를 더 도전적으로 설정할 것.")

    feedback["self_whip"] = whip_points

    # 투자 활동 인정 (자기 채찍질 속 위로)
    investment = [c for c in commits if c["impact_type"] == "investment"]
    if investment:
        feedback["investment_note"] = (
            f"투자 활동 {len(investment)}건 (테스트/인프라/학습). "
            "당장 임팩트는 아니지만 미래를 위한 합리적 투자."
        )

    return feedback


def run(input_data: dict, context: dict) -> dict:
    """주간 목표 관리자 실행"""
    action = input_data.get("action", "check")
    workdir = context.get("workdir", ".")

    if action == "declare":
        goals = input_data.get("goals", [])
        if not goals:
            return {"success": False, "message": "goals 파라미터가 필요합니다."}
        return declare_goals(goals)

    elif action == "check":
        return check_progress(workdir)

    elif action == "update":
        index = input_data.get("goal_index")
        if index is None:
            return {"success": False, "message": "goal_index가 필요합니다."}
        return update_goal(
            index,
            input_data.get("status"),
            input_data.get("progress_note"),
        )

    elif action == "evaluate":
        return evaluate_week(workdir)

    return {"success": False, "message": f"알 수 없는 action: {action}"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", type=str)
    parser.add_argument("--tool-context-json", type=str)

    args = parser.parse_args()

    if args.tool_spec_json:
        print(json.dumps(TOOL_SPEC, ensure_ascii=False, indent=2))
        sys.exit(0)

    input_data = json.loads(args.tool_input_json) if args.tool_input_json else {}
    context = json.loads(args.tool_context_json) if args.tool_context_json else {}

    result = run(input_data, context)
    print(json.dumps(result, ensure_ascii=False, indent=2))
