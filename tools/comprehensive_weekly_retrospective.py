#!/usr/bin/env python3
"""
Comprehensive Weekly Retrospective - 투명하고 강력한 회고 시스템

통합 요소:
1. Karpathy의 4가지 원칙 (Think, Simplicity, Surgical, Goal-Driven)
2. Bitter Lesson (프롬프트 품질 > 양, 학습 가능한 구조)
3. 전역 데이터 수집 (Claude Code, Codex, Git, Browser, Terminal)
4. 패턴 인사이트 + 메타 회고
"""

import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List
from collections import Counter

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "comprehensive_weekly_retrospective",
    "description": "Karpathy 원칙 + Bitter Lesson 기반 투명한 주간 회고",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "days_back": {
                "type": "integer",
                "description": "회고 기간 (일)",
                "default": 7
            },
            "output_format": {
                "type": "string",
                "enum": ["markdown", "json"],
                "description": "출력 형식",
                "default": "markdown"
            }
        }
    }
}


def collect_git_commits(days_back: int, workdir: str) -> List[Dict[str, Any]]:
    """Git 커밋 수집"""
    commits = []
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--pretty=format:%H|%ad|%s|%an", "--date=iso"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=10
        )

        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split('|', 3)
                if len(parts) == 4:
                    commits.append({
                        "hash": parts[0][:7],
                        "date": parts[1][:10],
                        "time": parts[1][11:19],
                        "message": parts[2],
                        "author": parts[3]
                    })
    except Exception:
        pass

    return commits


def analyze_karpathy_principles(prompts: List[Dict], commits: List[Dict]) -> Dict[str, Any]:
    """Karpathy 4가지 원칙 분석"""

    # 1. Think Before Coding (가정 vs 질문)
    questions = sum(1 for p in prompts if '?' in p.get('content', '') or any(
        word in p.get('content', '').lower()
        for word in ['어떻게', '왜', '뭐', '무엇', '언제', 'how', 'why', 'what']
    ))
    assumptions = len(prompts) - questions
    think_score = min(100, int((questions / len(prompts)) * 150)) if prompts else 0

    # 2. Simplicity First (코드 복잡도)
    # 커밋 메시지에서 리팩토링/단순화 키워드 찾기
    simplification_commits = sum(1 for c in commits if any(
        word in c['message'].lower()
        for word in ['리팩토링', '단순화', '정리', 'refactor', 'simplify', 'clean']
    ))
    simplicity_score = min(100, int((simplification_commits / max(len(commits), 1)) * 200))

    # 3. Surgical Changes (변경 범위)
    # 작은 커밋이 좋은 커밋 (메시지 길이로 추정)
    avg_commit_msg_length = sum(len(c['message']) for c in commits) / max(len(commits), 1) if commits else 0
    surgical_score = 100 if 20 <= avg_commit_msg_length <= 80 else 50

    # 4. Goal-Driven (측정 가능한 목표)
    # 구체적 목표가 있는 프롬프트/커밋 (숫자, 테스트, 완료 등)
    goal_keywords = ['테스트', '완료', '성공', '달성', '목표', 'test', 'pass', 'complete', 'done']
    goal_driven_count = sum(1 for p in prompts if any(
        word in p.get('content', '').lower() for word in goal_keywords
    ))
    goal_score = min(100, int((goal_driven_count / max(len(prompts), 1)) * 300))

    return {
        "think_before_coding": {
            "score": think_score,
            "questions": questions,
            "assumptions": assumptions,
            "advice": "✅ 질문형 프롬프트 비율 좋음" if think_score >= 70 else "⚠️ 가정보다 질문하기"
        },
        "simplicity_first": {
            "score": simplicity_score,
            "refactoring_commits": simplification_commits,
            "advice": "✅ 단순화 작업 진행 중" if simplicity_score >= 50 else "⚠️ 복잡도 줄이기"
        },
        "surgical_changes": {
            "score": surgical_score,
            "avg_commit_size": f"{avg_commit_msg_length:.1f}자",
            "advice": "✅ 적절한 커밋 크기" if surgical_score >= 70 else "⚠️ 더 작은 단위로 커밋"
        },
        "goal_driven": {
            "score": goal_score,
            "goal_oriented_prompts": goal_driven_count,
            "advice": "✅ 목표 지향적" if goal_score >= 60 else "⚠️ 측정 가능한 목표 설정"
        },
        "overall_score": int((think_score + simplicity_score + surgical_score + goal_score) / 4)
    }


def analyze_bitter_lesson(prompts: List[Dict], prev_week_prompts: List[Dict]) -> Dict[str, Any]:
    """Bitter Lesson 분석 (프롬프트 품질 > 양)"""

    # 프롬프트 길이 통계
    lengths = [len(p.get('content', '')) for p in prompts]
    avg_length = sum(lengths) / len(lengths) if lengths else 0

    # 품질 지표
    quality_indicators = {
        "길이 적정": 30 <= avg_length <= 200,
        "구체적": sum(1 for p in prompts if len(p.get('content', '').split()) > 10) / max(len(prompts), 1) > 0.5,
        "맥락 제공": sum(1 for p in prompts if any(
            word in p.get('content', '').lower()
            for word in ['때문에', '위해', '하려고', 'because', 'to', 'for']
        )) / max(len(prompts), 1) > 0.3
    }

    quality_score = sum(1 for v in quality_indicators.values() if v) * 33.3

    # 전주 대비 품질 개선
    prev_avg_length = sum(len(p.get('content', '')) for p in prev_week_prompts) / max(len(prev_week_prompts), 1) if prev_week_prompts else 0
    quality_trend = "📈 개선" if avg_length > prev_avg_length else "📉 유지" if avg_length == prev_avg_length else "📉 저하"

    # 버려야 할 스캐폴딩 감지 (반복되는 프롬프트 패턴)
    prompt_texts = [p.get('content', '')[:50].lower() for p in prompts]
    repeated = [text for text, count in Counter(prompt_texts).items() if count > 3]

    return {
        "quality_score": int(quality_score),
        "avg_prompt_length": f"{avg_length:.1f}자",
        "quality_indicators": quality_indicators,
        "quality_trend": quality_trend,
        "repeated_patterns": repeated[:3],  # 상위 3개
        "advice": [
            "✅ 프롬프트 품질 우수" if quality_score >= 70 else "⚠️ 프롬프트 품질 개선 필요",
            f"평균 길이 {avg_length:.0f}자 {'적정' if 30 <= avg_length <= 200 else '조정 필요'}",
            f"반복 패턴 {len(repeated)}개 발견 → 자동화 고려" if repeated else "✅ 패턴 반복 없음"
        ]
    }


def generate_insights(data: Dict[str, Any]) -> List[str]:
    """패턴 기반 인사이트 생성"""
    insights = []

    prompts = data.get('prompts', [])
    commits = data.get('commits', [])

    # 프롬프트 소스 분포
    sources = Counter(p.get('source') for p in prompts)
    if sources:
        main_source = sources.most_common(1)[0]
        insights.append(f"🎯 주력 도구: {main_source[0]} ({main_source[1]}개, {main_source[1]/len(prompts)*100:.1f}%)")

    # 커밋 집중도
    if commits:
        commit_dates = Counter(c['date'] for c in commits)
        if len(commit_dates) == 1:
            insights.append("⚠️ 모든 커밋이 하루에 집중 → 분산 권장")
        elif len(commit_dates) >= 5:
            insights.append("✅ 커밋이 여러 날에 분산 → 꾸준한 작업")

    # 프롬프트 타입 균형
    question_count = sum(1 for p in prompts if '?' in p.get('content', ''))
    command_count = sum(1 for p in prompts if '해줘' in p.get('content', '') or '만들어' in p.get('content', ''))

    if question_count > command_count * 2:
        insights.append("💡 질문형이 많음 → 탐색/학습 단계")
    elif command_count > question_count * 2:
        insights.append("🔨 지시형이 많음 → 실행 단계")
    else:
        insights.append("✅ 질문형/지시형 균형")

    # 프롬프트 품질 추이
    karpathy = data.get('karpathy_analysis', {})
    overall = karpathy.get('overall_score', 0)
    if overall >= 80:
        insights.append("🏆 Karpathy 원칙 준수 우수")
    elif overall >= 60:
        insights.append("📊 Karpathy 원칙 준수 양호")
    else:
        insights.append("⚠️ Karpathy 원칙 개선 필요")

    return insights


def generate_next_week_goals(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """다음 주 SMART 목표 생성"""
    goals = []

    prompts = data.get('prompts', [])
    commits = data.get('commits', [])
    karpathy = data.get('karpathy_analysis', {})
    bitter = data.get('bitter_lesson_analysis', {})

    # Goal 1: 커밋 목표
    current_commits = len(commits)
    target_commits = max(10, int(current_commits * 1.5))
    goals.append({
        "area": "코딩",
        "goal": f"커밋 {target_commits}개 이상 (현재 {current_commits}개)",
        "metric": f"git log --since='1 week ago' | grep '^commit' | wc -l >= {target_commits}"
    })

    # Goal 2: 프롬프트 품질
    quality_score = bitter.get('quality_score', 0)
    if quality_score < 70:
        goals.append({
            "area": "프롬프트 품질",
            "goal": "프롬프트 품질 점수 70점 이상",
            "metric": "평균 길이 30-200자, 맥락 제공, 구체적"
        })

    # Goal 3: Karpathy 원칙
    if karpathy.get('overall_score', 0) < 80:
        weak_principle = min(
            karpathy.items(),
            key=lambda x: x[1].get('score', 100) if isinstance(x[1], dict) else 100
        )
        goals.append({
            "area": "코딩 원칙",
            "goal": f"{weak_principle[0]} 개선",
            "metric": f"{weak_principle[1].get('advice', '')}"
        })

    # Goal 4: 균형
    goals.append({
        "area": "작업 분산",
        "goal": "매일 최소 1커밋",
        "metric": "연속 7일 커밋 기록"
    })

    return goals[:3]  # 상위 3개만


def run(input_data: dict, context: dict) -> dict:
    """종합 주간 회고 실행"""
    days_back = input_data.get("days_back", 7)
    output_format = input_data.get("output_format", "markdown")
    workdir = context.get("workdir", ".")

    # 1. 데이터 수집
    print("📊 데이터 수집 중...", file=sys.stderr)

    # 프롬프트 수집 (오늘 파일)
    today = datetime.now().strftime("%Y%m%d")
    prompts_file = Path(workdir) / "logs" / f"prompts_collected_{today}.jsonl"

    prompts = []
    if prompts_file.exists():
        with open(prompts_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    prompts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Git 커밋
    commits = collect_git_commits(days_back, workdir)

    # 전주 프롬프트 (비교용)
    prev_week_file = Path(workdir) / "logs" / f"prompts_collected_{(datetime.now() - timedelta(days=7)).strftime('%Y%m%d')}.jsonl"
    prev_prompts = []
    if prev_week_file.exists():
        with open(prev_week_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    prev_prompts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # 2. 분석
    print("🧠 분석 중...", file=sys.stderr)

    karpathy_analysis = analyze_karpathy_principles(prompts, commits)
    bitter_lesson_analysis = analyze_bitter_lesson(prompts, prev_prompts)

    data = {
        "prompts": prompts,
        "commits": commits,
        "karpathy_analysis": karpathy_analysis,
        "bitter_lesson_analysis": bitter_lesson_analysis
    }

    insights = generate_insights(data)
    next_week_goals = generate_next_week_goals(data)

    # 3. 출력 생성
    if output_format == "json":
        return {
            "success": True,
            "period": f"{days_back}일",
            "total_prompts": len(prompts),
            "total_commits": len(commits),
            "karpathy_analysis": karpathy_analysis,
            "bitter_lesson_analysis": bitter_lesson_analysis,
            "insights": insights,
            "next_week_goals": next_week_goals
        }

    # Markdown 출력
    lines = []
    lines.append(f"# 주간 회고 ({datetime.now().strftime('%Y-%m-%d')})")
    lines.append("")
    lines.append(f"> **Karpathy 원칙 + Bitter Lesson 기반 투명한 회고**")
    lines.append("")

    # Part 1: Raw Data
    lines.append("## 📊 Part 1: Raw Data (투명성)")
    lines.append("")
    lines.append(f"**기간**: 최근 {days_back}일")
    lines.append(f"**프롬프트**: {len(prompts)}개")
    lines.append(f"**커밋**: {len(commits)}개")
    lines.append("")

    # 프롬프트 소스별
    sources = Counter(p.get('source') for p in prompts)
    lines.append("**프롬프트 소스**:")
    for source, count in sources.most_common():
        lines.append(f"- {source}: {count}개 ({count/len(prompts)*100:.1f}%)")
    lines.append("")

    # Part 2: Karpathy 분석
    lines.append("## 🎯 Part 2: Karpathy 원칙 분석")
    lines.append("")
    lines.append(f"**종합 점수**: {karpathy_analysis['overall_score']}/100")
    lines.append("")

    for principle, details in karpathy_analysis.items():
        if principle == 'overall_score':
            continue
        if isinstance(details, dict):
            lines.append(f"### {principle.replace('_', ' ').title()}")
            lines.append(f"- **점수**: {details['score']}/100")
            lines.append(f"- **조언**: {details['advice']}")
            lines.append("")

    # Part 3: Bitter Lesson
    lines.append("## 💡 Part 3: Bitter Lesson 분석")
    lines.append("")
    lines.append(f"**프롬프트 품질 점수**: {bitter_lesson_analysis['quality_score']}/100")
    lines.append(f"**평균 길이**: {bitter_lesson_analysis['avg_prompt_length']}")
    lines.append(f"**품질 추이**: {bitter_lesson_analysis['quality_trend']}")
    lines.append("")
    lines.append("**조언**:")
    for advice in bitter_lesson_analysis['advice']:
        lines.append(f"- {advice}")
    lines.append("")

    # Part 4: 인사이트
    lines.append("## 🔍 Part 4: 패턴 인사이트")
    lines.append("")
    for insight in insights:
        lines.append(f"- {insight}")
    lines.append("")

    # Part 5: 다음 주 목표
    lines.append("## 🎯 Part 5: 다음 주 SMART 목표")
    lines.append("")
    for i, goal in enumerate(next_week_goals, 1):
        lines.append(f"### Goal {i}: {goal['area']}")
        lines.append(f"- **목표**: {goal['goal']}")
        lines.append(f"- **측정**: {goal['metric']}")
        lines.append("")

    # Part 6: 실행 체크리스트
    lines.append("## ✅ Part 6: 실행 체크리스트")
    lines.append("")
    lines.append("**이번 주 실행할 것**:")
    lines.append("- [ ] 매일 프롬프트 품질 체크")
    lines.append("- [ ] Karpathy 원칙 적용 (질문형 프롬프트)")
    lines.append("- [ ] 작은 단위로 커밋")
    lines.append("- [ ] 측정 가능한 목표 설정")
    lines.append("")

    markdown = "\n".join(lines)

    # 파일 저장
    output_file = Path(workdir) / f"weekly_retrospective_{datetime.now().strftime('%Y_week%W')}.md"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(markdown)

    return {
        "success": True,
        "output_file": str(output_file),
        "markdown": markdown,
        "summary": {
            "prompts": len(prompts),
            "commits": len(commits),
            "karpathy_score": karpathy_analysis['overall_score'],
            "quality_score": bitter_lesson_analysis['quality_score']
        }
    }


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
