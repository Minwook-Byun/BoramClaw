from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from reflexion_store import ReflexionStore

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "feedback_collector",
    "description": "BoramClaw의 제안/예측에 대한 사용자 평가를 기록합니다. '오늘 제안 도움됐어', '집중 시간 예측 틀렸어' 같은 자연어 피드백을 받습니다.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "feedback": {
                "type": "string",
                "description": "자유 형식 피드백 (Korean/English)",
            },
            "category": {
                "type": "string",
                "enum": ["productivity_advice", "time_prediction", "context_detection", "rule_trigger", "general"],
                "default": "general",
            },
            "rating": {
                "type": "integer",
                "description": "1-5 별점 (선택)",
                "minimum": 1,
                "maximum": 5,
            },
            "reference_date": {
                "type": "string",
                "description": "피드백이 참조하는 날짜 (YYYY-MM-DD, 기본값: 오늘)",
            },
        },
        "required": ["feedback"],
    },
}


def _extract_auto_tags(text: str) -> list[str]:
    lowered = (text or "").lower()
    tags: list[str] = []

    if any(token in lowered for token in ("맞아", "정확해", "정확했", "좋아", "accurate", "good", "helpful")):
        tags.append("positive")
    if any(token in lowered for token in ("틀렸어", "아니야", "부정확", "wrong", "inaccurate", "not correct")):
        tags.append("negative")
    if any(token in lowered for token in ("집중", "포모도로", "시간", "focus", "pomodoro", "time")):
        tags.append("time_management")
    if any(token in lowered for token in ("커밋", "git", "코드", "commit", "code")):
        tags.append("coding_habit")

    # 순서 유지 중복 제거
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    feedback = str(input_data.get("feedback", "")).strip()
    if not feedback:
        raise ValueError("feedback 필드는 필수입니다.")

    category = str(input_data.get("category", "general")).strip() or "general"
    rating_raw = input_data.get("rating")
    rating = None
    if rating_raw is not None:
        rating = int(rating_raw)
        if rating < 1 or rating > 5:
            raise ValueError("rating은 1~5 범위여야 합니다.")

    reference_date = str(input_data.get("reference_date", "")).strip() or date.today().isoformat()
    auto_tags = _extract_auto_tags(feedback)

    workdir = str(context.get("workdir", "."))
    store = ReflexionStore(workdir=workdir, file_path="logs/reflexion_cases.jsonl")
    store.add_feedback(text=feedback, source="user")

    row = {
        "ts": datetime.now().isoformat(),
        "category": category,
        "rating": rating,
        "feedback": feedback,
        "reference_date": reference_date,
        "auto_tags": auto_tags,
    }
    output_path = Path(workdir) / "logs" / "user_feedback.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "saved": True,
        "message": "피드백이 저장되었습니다. 다음 분석에 반영됩니다.",
        "tags": auto_tags,
    }


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
