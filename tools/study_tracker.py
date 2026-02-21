#!/usr/bin/env python3
"""
study_tracker.py
16주 ML 커리큘럼 진도 추적 툴

- 현재 주차 자동 계산 (config/study_plan.json 기준)
- Codex/Claude Code 프롬프트에서 학습 키워드 탐지
- 일간/주간 학습 증거 레포트 + 미달 시 경고
"""
import sys
import json
import argparse
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "study_tracker",
    "description": """16주 ML 커리큘럼 학습 진도를 추적하고 피드백을 제공합니다.

    매일 회고/주간 회고 때 자동으로 호출되어:
    - 현재 주차 및 이번 주 학습 주제 확인
    - Codex/Claude 대화에서 학습 키워드 탐지
    - 학습 증거(프롬프트) 요약
    - 목표 미달 시 경고 및 권고사항 제공

    학습 중인 논문: Attention → Scaling Laws → FlashAttention → KV Cache
    → LoRA → QLoRA → RLHF → MoE → vLLM → ZeRO → Tensor Parallel
    → Cost Model → RAG → ReAct → Toolformer → AX Architecture
    """,
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["daily", "weekly"],
                "description": "daily=오늘 학습 체크, weekly=이번 주 전체 진도",
                "default": "daily"
            },
            "days_back": {
                "type": "integer",
                "description": "몇 일치 프롬프트를 분석할지 (기본값: daily=1, weekly=7)",
                "default": 1
            },
            "override_week": {
                "type": "integer",
                "description": "주차 강제 지정 (테스트용, 보통 자동 계산)",
                "default": None
            }
        },
        "required": []
    }
}

# 학습 증거 임계값
MIN_STUDY_PROMPTS_DAILY = 3       # 하루 최소 학습 관련 프롬프트 수
MIN_STUDY_PROMPTS_WEEKLY = 15     # 주간 최소 학습 관련 프롬프트 수
STUDY_PLAN_PATH = Path(__file__).parent.parent / "config" / "study_plan.json"


def load_study_plan() -> Optional[Dict]:
    """study_plan.json 로드"""
    if not STUDY_PLAN_PATH.exists():
        return None
    try:
        return json.loads(STUDY_PLAN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_current_week_info(plan: Dict, override_week: Optional[int] = None) -> Dict:
    """
    오늘 날짜 기준으로 현재 주차와 해당 주 학습 정보 반환.
    아직 시작 안 됐거나 커리큘럼 완료 시 적절한 메시지 반환.
    """
    start_date = datetime.strptime(plan["start_date"], "%Y-%m-%d")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if override_week:
        week_num = override_week
    else:
        delta = (today - start_date).days
        if delta < 0:
            days_until = -delta
            return {
                "status": "not_started",
                "message": f"커리큘럼이 {plan['start_date']}에 시작됩니다 (D-{days_until})",
                "start_date": plan["start_date"],
                "week": 0
            }
        week_num = (delta // 7) + 1

    total_weeks = plan.get("total_weeks", 16)
    if week_num > total_weeks:
        return {
            "status": "completed",
            "message": f"🎉 16주 커리큘럼 완료! (마지막 주: Week {total_weeks})",
            "week": week_num
        }

    # 해당 주차의 상세 정보 찾기
    week_info = None
    phase_info = None
    for phase in plan.get("phases", []):
        for w in phase.get("weeks", []):
            if w["week"] == week_num:
                week_info = w
                phase_info = phase
                break
        if week_info:
            break

    if not week_info:
        return {"status": "unknown", "week": week_num}

    # 해당 주 날짜 범위
    week_start = start_date + timedelta(weeks=week_num - 1)
    week_end = week_start + timedelta(days=6)

    return {
        "status": "active",
        "week": week_num,
        "phase": phase_info["phase"],
        "phase_name": phase_info["name"],
        "topic": week_info["topic"],
        "paper": week_info["paper"],
        "goal": week_info["goal"],
        "deliverable": week_info["deliverable"],
        "keywords": week_info["keywords"],
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": week_end.strftime("%Y-%m-%d"),
    }


def get_all_week_keywords(plan: Dict, up_to_week: int) -> Dict[int, List[str]]:
    """주차별 키워드 맵 반환 (누적 학습 체크용)"""
    result = {}
    for phase in plan.get("phases", []):
        for w in phase.get("weeks", []):
            if w["week"] <= up_to_week:
                result[w["week"]] = w["keywords"]
    return result


def collect_recent_prompts(days_back: int, workdir: str) -> List[Dict]:
    """최근 N일 프롬프트 수집 (prompts_collected_*.jsonl 파일에서)"""
    prompts = []
    logs_dir = Path(workdir) / "logs"
    if not logs_dir.exists():
        return prompts

    cutoff = datetime.now() - timedelta(days=days_back)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # 최근 파일들 탐색
    for jsonl_file in sorted(logs_dir.glob("prompts_collected_*.jsonl"), reverse=True):
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        p = json.loads(line.strip())
                        if p.get("date", "") >= cutoff_str:
                            prompts.append(p)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue

    return prompts


def detect_study_prompts(
    prompts: List[Dict],
    keywords: List[str],
    week_topic: str
) -> Tuple[List[Dict], List[Dict]]:
    """
    프롬프트 리스트에서 학습 관련 프롬프트 탐지.
    Returns: (matched_prompts, high_quality_matches)
    """
    matched = []
    lower_keywords = [kw.lower() for kw in keywords]

    for p in prompts:
        content = (p.get("content", "") or p.get("full_content", "") or "").lower()
        if not content:
            continue

        # 키워드 매칭
        matched_kws = [kw for kw in lower_keywords if kw in content]
        if matched_kws:
            p_copy = dict(p)
            p_copy["_matched_keywords"] = matched_kws[:5]
            p_copy["_match_count"] = len(matched_kws)
            matched.append(p_copy)

    # 매칭 수 기준 정렬 (많이 매칭될수록 더 관련성 높음)
    matched.sort(key=lambda x: x["_match_count"], reverse=True)

    # 고품질 매칭: 2개 이상 키워드 매칭 or 내용이 구체적
    high_quality = [p for p in matched if p["_match_count"] >= 2 or len(p.get("content", "")) > 50]

    return matched, high_quality


def build_study_report(
    mode: str,
    week_info: Dict,
    prompts: List[Dict],
    days_back: int
) -> Dict:
    """학습 진도 레포트 생성"""
    if week_info.get("status") != "active":
        return {
            "success": True,
            "status": week_info.get("status"),
            "message": week_info.get("message", ""),
            "week": week_info.get("week", 0)
        }

    week_num = week_info["week"]
    topic = week_info["topic"]
    keywords = week_info["keywords"]

    # Codex 프롬프트만 필터 (학습은 주로 Codex로)
    codex_prompts = [p for p in prompts if "codex" in str(p.get("source", "")).lower()]
    claude_prompts = [p for p in prompts if "claude" in str(p.get("source", "")).lower()]
    all_study_prompts = codex_prompts + claude_prompts

    matched, high_quality = detect_study_prompts(all_study_prompts, keywords, topic)

    # 임계값 및 경고 계산
    threshold = MIN_STUDY_PROMPTS_DAILY if mode == "daily" else MIN_STUDY_PROMPTS_WEEKLY
    period_label = "오늘" if mode == "daily" else "이번 주"
    match_count = len(matched)
    hq_count = len(high_quality)

    # 경고 레벨 결정
    if match_count == 0:
        warning_level = "🔴 CRITICAL"
        warning_msg = f"{period_label} {topic} 관련 학습 기록이 전혀 없습니다. Codex에게 논문 내용을 물어보세요!"
    elif match_count < threshold // 2:
        warning_level = "🟠 WARNING"
        warning_msg = f"{period_label} 학습량이 목표의 {int(match_count / threshold * 100)}% 수준입니다. 더 질문해보세요."
    elif match_count < threshold:
        warning_level = "🟡 CAUTION"
        warning_msg = f"{period_label} {match_count}개 감지 (목표: {threshold}개). 조금 더 파고드세요."
    else:
        warning_level = "🟢 GOOD"
        warning_msg = f"{period_label} 학습 목표 달성! ({match_count}개 / 목표 {threshold}개)"

    # 대표 학습 프롬프트 샘플 (최대 5개)
    sample_prompts = []
    for p in matched[:5]:
        sample_prompts.append({
            "source": p.get("source", "?"),
            "date": p.get("date", ""),
            "time": p.get("time", ""),
            "content": (p.get("content", "") or "")[:120],
            "matched_keywords": p.get("_matched_keywords", [])
        })

    # Codex 추천 질문 (학습 키워드 기반)
    suggested_questions = _build_suggested_questions(topic, keywords, week_info)

    return {
        "success": True,
        "status": "active",
        "week": week_num,
        "phase": week_info["phase"],
        "phase_name": week_info["phase_name"],
        "topic": topic,
        "paper": week_info["paper"],
        "goal": week_info["goal"],
        "deliverable": week_info["deliverable"],
        "week_range": f"{week_info['week_start']} ~ {week_info['week_end']}",
        "study_evidence": {
            "total_matched": match_count,
            "high_quality_matched": hq_count,
            "threshold": threshold,
            "sample_prompts": sample_prompts
        },
        "warning": {
            "level": warning_level,
            "message": warning_msg
        },
        "suggested_questions": suggested_questions,
        "raw_prompt_count": {
            "codex": len(codex_prompts),
            "claude": len(claude_prompts),
            "total": len(all_study_prompts)
        }
    }


def _build_suggested_questions(topic: str, keywords: List[str], week_info: Dict) -> List[str]:
    """주제별 Codex에게 물어볼 추천 질문 생성"""
    goal = week_info.get("goal", "")
    deliverable = week_info.get("deliverable", "")

    suggestions = {
        "Attention 구조": [
            "Transformer의 Q, K, V 행렬이 각각 무슨 역할을 하는지 수식과 함께 설명해줘",
            "Self-attention의 계산 복잡도가 O(n²)인 이유를 직관적으로 설명해줘",
            "Multi-head attention에서 헤드를 여러 개 쓰는 이유가 뭐야?",
            "Scaled dot-product attention에서 √dk로 나누는 이유 설명해줘"
        ],
        "Scaling Laws": [
            "Kaplan 2020 Scaling Laws에서 compute-optimal 학습이 뭔지 설명해줘",
            "파라미터 수가 2배 늘면 VRAM은 얼마나 더 필요해? 계산해줘",
            "Chinchilla 논문이 GPT-3 학습 방식의 어떤 문제를 지적했어?",
            "7B 모델을 full precision(fp32)으로 로드하면 VRAM이 얼마나 필요해?"
        ],
        "FlashAttention": [
            "FlashAttention이 naive attention 대비 메모리를 줄이는 핵심 아이디어가 뭐야?",
            "GPU의 HBM과 SRAM 차이가 뭐고 왜 attention이 memory-bound야?",
            "FlashAttention의 tiling 방식을 수식 없이 직관적으로 설명해줘",
            "FlashAttention v2에서 v1 대비 뭐가 개선됐어?"
        ],
        "KV Cache": [
            "KV cache가 없으면 autoregressive generation이 왜 느린지 설명해줘",
            "대화 길이가 2배 늘면 KV cache 메모리는 얼마나 늘어나? 계산해줘",
            "Prefill과 decode 단계의 차이가 뭐야?",
            "긴 컨텍스트에서 KV cache가 VRAM을 얼마나 차지하는지 llama-7b 기준으로 계산해줘"
        ],
        "LoRA": [
            "LoRA에서 W를 A×B로 분해하는 수학적 직관이 뭐야?",
            "rank=8 LoRA가 full fine-tuning 대비 trainable parameter를 얼마나 줄여?",
            "LoRA를 attention의 어느 행렬에 적용하면 효과가 가장 크고 왜?",
            "LoRA 학습 후 추론 시 병합하는 방식 설명해줘"
        ],
        "QLoRA": [
            "NF4 quantization이 int4 대비 어떤 점에서 더 좋아?",
            "Double quantization이 뭐고 메모리를 얼마나 절약해?",
            "7B 모델을 4bit로 로드하면 VRAM이 얼마나 필요해? 16bit와 비교해줘",
            "Paged optimizer가 OOM을 어떻게 방지해?"
        ],
        "RLHF": [
            "RLHF 파이프라인의 3단계(SFT→RM→PPO)를 각각 설명해줘",
            "Reward Model은 어떻게 학습하고 뭘 예측해?",
            "PPO가 RLHF에서 왜 사용되고 KL divergence는 왜 필요해?",
            "InstructGPT vs GPT-3 성능 차이가 왜 나는지 alignment 관점에서 설명해줘"
        ],
        "Mixture of Experts": [
            "MoE에서 router가 expert를 선택하는 방식이 어떻게 돼?",
            "Switch Transformer가 기존 MoE 대비 뭘 단순화했어?",
            "7B×8 MoE 모델(Mixtral)의 active parameter가 실제로 몇 B야?",
            "Dense 70B vs MoE 8×7B: VRAM과 추론 속도 비교해줘"
        ],
        "PagedAttention": [
            "vLLM의 PagedAttention이 기존 KV cache 방식의 어떤 문제를 해결해?",
            "메모리 단편화(fragmentation)가 LLM serving에서 왜 문제야?",
            "Continuous batching이 static batching 대비 throughput이 높은 이유는?",
            "vLLM과 TGI(Text Generation Inference) 아키텍처 차이 설명해줘"
        ],
        "DeepSpeed ZeRO": [
            "ZeRO Stage 1, 2, 3의 차이를 파라미터/그래디언트/옵티마이저 상태 기준으로 설명해줘",
            "8개 A100에서 ZeRO-3로 70B 모델 학습하면 GPU당 메모리가 얼마나 필요해?",
            "ZeRO-Infinity가 ZeRO-3와 다른 점이 뭐야?",
            "Gradient checkpointing과 ZeRO를 함께 쓸 때 장단점이 뭐야?"
        ],
        "Tensor Parallelism": [
            "Tensor parallelism에서 column-parallel과 row-parallel linear layer가 뭐야?",
            "파이프라인 병렬화의 bubble overhead가 뭐고 어떻게 줄여?",
            "데이터/텐서/파이프라인 병렬화 중 언제 뭘 써야 해?",
            "Megatron-LM에서 4-way tensor parallel 설정하면 통신 비용이 얼마나 발생해?"
        ],
        "Cost Modeling": [
            "GPT-4 API로 월 100만 토큰 쓰는 것 vs A10G self-host 비용 비교해줘",
            "7B 모델을 단일 A10G(24GB)에서 서빙할 때 처리 가능한 동시 요청 수는?",
            "회사에서 LLM self-host 결정 시 고려할 TCO 항목들 나열해줘",
            "H100 vs A100 가격 대비 성능 비교 (LLM inference 기준)"
        ],
        "RAG": [
            "RAG가 fine-tuning 대비 hallucination을 줄이는 원리가 뭐야?",
            "Chunk size를 어떻게 정해야 해? 너무 크거나 작으면 어떤 문제가 생겨?",
            "Dense retrieval vs sparse retrieval (BM25) 차이와 언제 뭘 써야 해?",
            "RAG에서 retrieval 품질을 평가하는 지표가 뭐야?"
        ],
        "ReAct": [
            "ReAct의 Thought-Action-Observation 루프를 구체적인 예시로 설명해줘",
            "Chain-of-Thought와 ReAct의 핵심 차이가 뭐야?",
            "ReAct에서 tool call이 실패하면 어떻게 처리해?",
            "ReAct 패턴을 Claude API로 구현하는 최소 예시 코드 보여줘"
        ],
        "Tool Use & Planning": [
            "Toolformer가 tool 사용을 어떻게 학습하는지 설명해줘",
            "OpenAI function calling vs Anthropic tool use의 구현 차이가 뭐야?",
            "LLM이 어떤 tool을 쓸지 결정하는 방식 (routing) 설명해줘",
            "Tool use + RAG를 결합한 agentic 시스템 설계해줘"
        ],
        "전체 설계 통합": [
            "70B 모델을 4bit 양자화해서 vLLM으로 서빙할 때 필요한 GPU 스펙 계산해줘",
            "AX 용도로 self-hosted LLM 아키텍처 설계: 사용자 1000명, p50 latency 2초 이하",
            "API vs self-host 결정 트리를 만들어줘 (비용/레이턴시/보안 기준)",
            "내가 만들 AX 시스템의 end-to-end 아키텍처 다이어그램 그려줘 (텍스트)"
        ]
    }

    return suggestions.get(topic, [
        f"{topic}의 핵심 개념을 수식과 함께 설명해줘",
        f"{topic}을 실제 코드로 어떻게 구현해?",
        f"{topic}이 왜 중요한지, 이게 없으면 어떤 문제가 생겨?",
        f"{week_info.get('deliverable', '학습 결과물')}을 만들기 위해 뭐부터 시작해야 해?"
    ])


def run(input_data: dict, context: dict) -> Any:
    """학습 진도 추적 실행"""
    mode = input_data.get("mode", "daily")
    days_back = input_data.get("days_back", 1 if mode == "daily" else 7)
    override_week = input_data.get("override_week")
    workdir = context.get("workdir", str(Path(__file__).parent.parent))

    # 1. 학습 계획 로드
    plan = load_study_plan()
    if not plan:
        return {
            "success": False,
            "error": f"study_plan.json을 찾을 수 없습니다: {STUDY_PLAN_PATH}",
            "hint": "config/study_plan.json이 존재하는지 확인하세요"
        }

    # 2. 현재 주차 정보
    week_info = get_current_week_info(plan, override_week)

    # 시작 전이거나 완료된 경우 early return
    if week_info.get("status") in ("not_started", "completed", "unknown"):
        return {
            "success": True,
            "tracking": week_info
        }

    # 3. 프롬프트 수집
    prompts = collect_recent_prompts(days_back + 1, workdir)  # +1: 당일 포함

    # 4. 레포트 생성
    tracking = build_study_report(mode, week_info, prompts, days_back)

    # 5. 누적 진도 (완료된 주차 요약)
    current_week = week_info["week"]
    if current_week > 1:
        completed_weeks = []
        week_kw_map = get_all_week_keywords(plan, current_week - 1)
        for w_num, kws in week_kw_map.items():
            # 지난 주차의 학습 흔적은 전체 기간에서 체크
            w_prompts = collect_recent_prompts(days_back + (current_week - w_num) * 7, workdir)
            w_matched, _ = detect_study_prompts(w_prompts, kws, "")
            completed_weeks.append({
                "week": w_num,
                "found_prompts": len(w_matched)
            })
        tracking["completed_weeks_summary"] = completed_weeks

    return {
        "success": True,
        "tracking": tracking
    }


def format_report_markdown(tracking: Dict) -> str:
    """회고 리포트용 마크다운 섹션 생성"""
    lines = []
    lines.append("## 📚 ML 학습 진도 체크")
    lines.append("")

    status = tracking.get("status", "unknown")

    if status == "not_started":
        lines.append(f"⏳ {tracking.get('message', '')}")
        return "\n".join(lines)

    if status == "completed":
        lines.append(f"🎉 {tracking.get('message', '16주 완료!')}")
        return "\n".join(lines)

    week = tracking.get("week", "?")
    topic = tracking.get("topic", "?")
    phase_name = tracking.get("phase_name", "?")
    week_range = tracking.get("week_range", "")
    goal = tracking.get("goal", "")
    deliverable = tracking.get("deliverable", "")

    lines.append(f"### Week {week}: {topic}")
    lines.append(f"**Phase {tracking.get('phase', '?')}**: {phase_name} | {week_range}")
    lines.append(f"**논문**: {tracking.get('paper', '')}")
    lines.append(f"**이번 주 목표**: {goal}")
    lines.append(f"**산출물**: {deliverable}")
    lines.append("")

    # 경고
    warning = tracking.get("warning", {})
    lines.append(f"{warning.get('level', '')} {warning.get('message', '')}")
    lines.append("")

    # 학습 증거
    evidence = tracking.get("study_evidence", {})
    matched = evidence.get("total_matched", 0)
    hq = evidence.get("high_quality_matched", 0)
    threshold = evidence.get("threshold", 0)
    lines.append(f"**학습 프롬프트**: {matched}개 감지 (고품질: {hq}개 / 목표: {threshold}개)")

    sample = evidence.get("sample_prompts", [])
    if sample:
        lines.append("")
        lines.append("**학습 흔적 (상위 3개)**:")
        for p in sample[:3]:
            kws = ", ".join(p.get("matched_keywords", []))
            content = p.get("content", "")[:80]
            lines.append(f'- [{p.get("source","")} {p.get("time","")}] "{content}" → `{kws}`')

    # 추천 질문
    suggestions = tracking.get("suggested_questions", [])
    if suggestions and matched < MIN_STUDY_PROMPTS_DAILY:
        lines.append("")
        lines.append("**💡 Codex에게 이렇게 물어보세요**:")
        for q in suggestions[:3]:
            lines.append(f'- "{q}"')

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=TOOL_SPEC["description"])
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", type=str)
    parser.add_argument("--tool-context-json", type=str, default="{}")
    args = parser.parse_args()

    if args.tool_spec_json:
        print(json.dumps(TOOL_SPEC, ensure_ascii=False, indent=2))
        return

    if not args.tool_input_json:
        input_data = {}
    else:
        input_data = json.loads(args.tool_input_json)

    context = json.loads(args.tool_context_json)
    result = run(input_data, context)

    # CLI 출력 시 마크다운 형식도 함께 출력
    tracking = result.get("tracking", {})
    if tracking and tracking.get("status") == "active":
        print(format_report_markdown(tracking))
        print("")
        print("---")
        print("(JSON 상세)")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
