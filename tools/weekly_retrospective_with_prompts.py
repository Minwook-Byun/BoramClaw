#!/usr/bin/env python3
"""
Weekly Retrospective with Prompts - 프롬프트 데이터를 포함한 주간 회고

기존 회고 + 프롬프트 패턴 분석 통합
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import Counter

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "weekly_retrospective_with_prompts",
    "description": "프롬프트 데이터를 포함한 투명한 주간 회고를 생성합니다",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "include_prompt_analysis": {
                "type": "boolean",
                "description": "프롬프트 패턴 분석 포함 여부",
                "default": True
            }
        }
    }
}


def analyze_prompts(prompts_file: Path) -> dict:
    """수집된 프롬프트 분석"""
    if not prompts_file.exists():
        return {
            "error": "프롬프트 데이터 없음",
            "message": "먼저 universal_prompt_collector를 실행하세요"
        }

    prompts = []
    with open(prompts_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                prompts.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not prompts:
        return {"error": "프롬프트 없음"}

    # 프로젝트별 분포
    projects = Counter(p.get("project", "N/A") for p in prompts)

    # 소스별 분포
    sources = Counter(p.get("source") for p in prompts)

    # 길이 통계
    lengths = [len(p.get("content", "")) for p in prompts]
    avg_length = sum(lengths) / len(lengths) if lengths else 0

    # 자주 나오는 키워드 (간단 분석)
    all_words = []
    for p in prompts:
        content = p.get("content", "").lower()
        # 간단한 한글/영어 키워드 추출
        words = [w for w in content.split() if len(w) > 2 and w.isalpha()]
        all_words.extend(words)

    top_keywords = Counter(all_words).most_common(20)

    # 프롬프트 패턴 감지 (간단)
    patterns = {
        "질문형": sum(1 for p in prompts if '?' in p.get("content", "") or '뭐' in p.get("content", "") or '어떻게' in p.get("content", "")),
        "지시형": sum(1 for p in prompts if '해줘' in p.get("content", "") or '만들어' in p.get("content", "") or '추가' in p.get("content", "")),
        "검토형": sum(1 for p in prompts if '확인' in p.get("content", "") or '리뷰' in p.get("content", "") or '체크' in p.get("content", "")),
    }

    return {
        "total": len(prompts),
        "projects": dict(projects),
        "sources": dict(sources),
        "avg_length": round(avg_length, 1),
        "patterns": patterns,
        "top_keywords": top_keywords[:10],
        "samples": prompts[:5]  # 최근 5개 샘플
    }


def run(input_data: dict, context: dict) -> dict:
    """프롬프트 분석 포함 주간 회고"""
    workdir = Path(context.get("workdir", "."))

    # 오늘 날짜의 프롬프트 파일 찾기
    today = datetime.now().strftime("%Y%m%d")
    prompts_file = workdir / "logs" / f"prompts_collected_{today}.jsonl"

    # 프롬프트 분석
    analysis = analyze_prompts(prompts_file)

    if "error" in analysis:
        return {
            "success": False,
            "message": analysis["message"],
            "recommendation": "먼저 /tool universal_prompt_collector 실행하세요"
        }

    # 프롬프트 인사이트 생성
    insights = []

    # 1. 프로젝트 집중도
    if analysis["projects"]:
        main_project = max(analysis["projects"].items(), key=lambda x: x[1])
        total = analysis["total"]
        focus_rate = (main_project[1] / total) * 100
        insights.append(f"주력 프로젝트: {main_project[0]} ({focus_rate:.1f}% 집중)")

    # 2. 평균 프롬프트 길이
    if analysis["avg_length"] < 30:
        insights.append("⚠️ 프롬프트가 너무 짧음 → 맥락 부족 가능성")
    elif analysis["avg_length"] > 200:
        insights.append("⚠️ 프롬프트가 너무 김 → 핵심 불명확")
    else:
        insights.append("✅ 프롬프트 길이 적정")

    # 3. 패턴 분석
    if analysis["patterns"]:
        dominant_pattern = max(analysis["patterns"].items(), key=lambda x: x[1])
        insights.append(f"주요 패턴: {dominant_pattern[0]} ({dominant_pattern[1]}회)")

    # 4. 프롬프트 품질 점수 (간단 계산)
    quality_score = 0
    if 30 <= analysis["avg_length"] <= 200:
        quality_score += 30
    if analysis["patterns"].get("질문형", 0) > 0:
        quality_score += 20
    if analysis["sources"].get("log_md", 0) > 0:  # 수동 큐레이션 있으면 가점
        quality_score += 30
    if len(analysis["top_keywords"]) > 5:
        quality_score += 20

    insights.append(f"프롬프트 품질 점수: {quality_score}/100")

    return {
        "success": True,
        "prompt_analysis": analysis,
        "insights": insights,
        "recommendations": [
            "log.md에 핵심 프롬프트 계속 기록하기",
            f"평균 길이 {analysis['avg_length']:.0f}자 유지",
            "질문형/지시형/검토형 균형 맞추기"
        ]
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
