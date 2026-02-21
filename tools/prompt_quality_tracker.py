#!/usr/bin/env python3
"""
Prompt Quality Tracker - 프롬프트 품질을 측정하고 개선하는 도구

Bitter Lesson 적용:
- 복잡한 자동 수집 X
- 단순한 품질 메트릭 측정 O
- 관찰 → 패턴 발견 → 개선
"""

import json
import sys
from datetime import datetime
from pathlib import Path

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "prompt_quality_tracker",
    "description": "프롬프트 품질을 측정하고 기록합니다 (간결성, 명확성, 재현성)",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "측정할 프롬프트"
            },
            "result_summary": {
                "type": "string",
                "description": "결과 요약 (성공/실패, 길이 등)"
            },
            "retry_count": {
                "type": "integer",
                "description": "재시도 횟수 (0이 이상적)",
                "default": 0
            },
            "satisfaction": {
                "type": "integer",
                "description": "만족도 (1-5)",
                "minimum": 1,
                "maximum": 5,
                "default": 3
            },
            "pattern_name": {
                "type": "string",
                "description": "발견한 패턴 이름 (선택, 예: '제약_기반_요청')"
            }
        },
        "required": ["prompt"]
    }
}


def run(input_data: dict, context: dict) -> dict:
    """프롬프트 품질 기록"""
    prompt = input_data["prompt"]
    result_summary = input_data.get("result_summary", "")
    retry_count = input_data.get("retry_count", 0)
    satisfaction = input_data.get("satisfaction", 3)
    pattern_name = input_data.get("pattern_name", "")

    # 메트릭 계산
    prompt_length = len(prompt)
    is_clear = retry_count == 0  # 재시도 없으면 명확함
    is_concise = prompt_length < 100  # 100자 미만이면 간결
    is_satisfactory = satisfaction >= 4  # 4점 이상이면 만족

    # JSONL 로그에 기록
    log_dir = Path(context.get("workdir", ".")) / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "prompt_quality.jsonl"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt,
        "prompt_length": prompt_length,
        "result_summary": result_summary,
        "retry_count": retry_count,
        "satisfaction": satisfaction,
        "pattern_name": pattern_name,
        "metrics": {
            "clear": is_clear,
            "concise": is_concise,
            "satisfactory": is_satisfactory
        }
    }

    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    return {
        "success": True,
        "metrics": {
            "prompt_length": prompt_length,
            "clear": is_clear,
            "concise": is_concise,
            "satisfactory": is_satisfactory,
            "quality_score": sum([is_clear, is_satisfactory]) / 2.0
        },
        "message": f"품질 기록됨: {satisfaction}/5점, 재시도 {retry_count}회"
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prompt Quality Tracker")
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
