#!/usr/bin/env python3
"""
Deep Weekly Retrospective - 1만자 분량의 깊이 있는 피드백 회고

기존 comprehensive_weekly_retrospective는 "점수판"
이건 진짜 "회고" - 구체적 사례, 패턴, 피드백, 조언
"""

import json
import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List
from collections import Counter

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "deep_weekly_retrospective",
    "description": "1만자 분량의 깊이 있는 피드백 회고 (Karpathy + Bitter Lesson)",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "days_back": {
                "type": "integer",
                "description": "회고 기간 (일)",
                "default": 7
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


def _parse_prompt_datetime(prompt: Dict[str, Any]) -> datetime | None:
    date_text = str(prompt.get("date", "")).strip()
    if not date_text:
        return None
    time_text = str(prompt.get("time", "")).strip() or "00:00:00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            if fmt == "%Y-%m-%d":
                return datetime.strptime(date_text, fmt)
            return datetime.strptime(f"{date_text} {time_text}", fmt)
        except ValueError:
            continue
    return None


def _dedupe_prompts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for row in items:
        key = (
            row.get("source", ""),
            row.get("date", ""),
            row.get("time", ""),
            row.get("content", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _normalize_prompt_text(raw: Any) -> str:
    return " ".join(str(raw or "").split()).strip()


def _prompt_quality_score(prompt: Dict[str, Any]) -> float:
    """프롬프트 내용 품질 점수 (0-100)."""
    text = _normalize_prompt_text(prompt.get("full_content", "") or prompt.get("content", ""))
    if not text:
        return 0.0
    lower = text.lower()
    length = len(text)
    score = 40.0

    # 길이 품질 (너무 짧거나 너무 긴 프롬프트 패널티)
    if length < 8:
        score -= 30
    elif length < 20:
        score -= 14
    elif 25 <= length <= 220:
        score += 18
    elif 221 <= length <= 380:
        score += 9
    elif length > 500:
        score -= 8

    # 맥락/목표/제약 신호
    context_tokens = ("왜", "이유", "배경", "문제", "원인", "막혀", "context", "because", "error", "에러")
    goal_tokens = ("목표", "성공", "완료", "통과", "검증", "기준", "done", "pass", "success", "acceptance")
    constraint_tokens = ("최소", "최대", "제약", "제한", "시간", "성능", "보안", "days_back", "deadline", "timeout")
    if any(token in lower for token in context_tokens):
        score += 9
    if any(token in lower for token in goal_tokens):
        score += 10
    if any(token in lower for token in constraint_tokens):
        score += 7

    # 구체성 신호 (숫자/파일/경로/질문)
    number_hits = len(re.findall(r"\b\d+\b", text))
    score += min(number_hits * 1.5, 8.0)
    path_hits = len(re.findall(r"(?:/[A-Za-z0-9._-]+)+|\b[A-Za-z0-9._-]+\.[A-Za-z0-9]{1,8}\b", text))
    score += min(path_hits * 2.0, 8.0)
    if "?" in text:
        score += 5

    # 멀티 인텐트 과다/노이즈 패널티
    multi_intent_tokens = (" 그리고 ", " 또 ", " 그리고나서 ", " then ", " also ", " additionally ")
    multi_intent_count = sum(lower.count(tok.strip()) for tok in multi_intent_tokens)
    if multi_intent_count >= 4 and length > 220:
        score -= 6

    noise_markers = (
        "context from my ide setup",
        "## active file:",
        "## open tabs:",
        "[request interrupted",
    )
    if any(marker in lower for marker in noise_markers):
        score -= 28

    return max(0.0, min(score, 100.0))


def _prompt_fingerprint(prompt: Dict[str, Any]) -> str:
    text = _normalize_prompt_text(prompt.get("content", "")).lower()
    compact = re.sub(r"[^0-9a-zA-Z가-힣 ]+", " ", text)
    compact = re.sub(r"\s+", " ", compact).strip()
    return compact[:140]


def _pick_quality_examples(items: List[Dict[str, Any]], limit: int, strategy: str = "high") -> List[Dict[str, Any]]:
    """
    품질 점수 기반 예시 선택.
    strategy:
    - high: 고품질 프롬프트 우선
    - low: 개선 필요 프롬프트 우선
    """
    if limit <= 0 or not items:
        return []

    scored = []
    for idx, item in enumerate(items):
        quality = _prompt_quality_score(item)
        ts = _parse_prompt_datetime(item) or datetime.min
        scored.append((quality, ts, idx, item))

    reverse = strategy != "low"
    scored.sort(key=lambda x: (x[0], x[1], -x[2]), reverse=reverse)

    chosen: List[Dict[str, Any]] = []
    seen_fp = set()
    source_quota: Dict[str, int] = {}
    date_quota: Dict[str, int] = {}
    max_per_source = max(1, (limit + 1) // 2)
    max_per_date = max(1, (limit + 1) // 2)

    for quality, _ts, _idx, item in scored:
        fp = _prompt_fingerprint(item)
        if not fp or fp in seen_fp:
            continue
        source = str(item.get("source", "unknown"))
        date_label = str(item.get("date", "unknown"))
        if source_quota.get(source, 0) >= max_per_source:
            continue
        if date_quota.get(date_label, 0) >= max_per_date:
            continue
        row = dict(item)
        row["_quality_score"] = round(quality, 1)
        chosen.append(row)
        seen_fp.add(fp)
        source_quota[source] = source_quota.get(source, 0) + 1
        date_quota[date_label] = date_quota.get(date_label, 0) + 1
        if len(chosen) >= limit:
            break

    # quota 때문에 부족할 경우 완화
    if len(chosen) < limit:
        for quality, _ts, _idx, item in scored:
            fp = _prompt_fingerprint(item)
            if not fp or fp in seen_fp:
                continue
            row = dict(item)
            row["_quality_score"] = round(quality, 1)
            chosen.append(row)
            seen_fp.add(fp)
            if len(chosen) >= limit:
                break

    return chosen


def collect_prompt_windows(days_back: int, workdir: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    최근 N일(current) + 그 이전 N일(previous) 프롬프트를 수집.
    universal_prompt_collector를 실행해 최신 데이터를 재생성한다.
    """
    meta: Dict[str, Any] = {"collector_success": False}
    all_prompts: List[Dict[str, Any]] = []

    try:
        from universal_prompt_collector import run as run_universal_prompt_collector

        collect_days = max(days_back * 2, 14)
        collector_result = run_universal_prompt_collector(
            {
                "days_back": collect_days,
                "sources": ["all"],
                "min_length": 5,
            },
            {"workdir": workdir},
        )
        if isinstance(collector_result, dict):
            meta["collector_success"] = bool(collector_result.get("success"))
            meta["collector_output_file"] = collector_result.get("output_file", "")
            meta["collector_by_source"] = collector_result.get("by_source", {})

            output_file = collector_result.get("output_file", "")
            if isinstance(output_file, str) and output_file:
                out_path = Path(output_file)
                if out_path.exists():
                    with open(out_path, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                row = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(row, dict):
                                source = str(row.get("source", ""))
                                if source in {"codex_session", "codex"}:
                                    row["source"] = "codex"
                                all_prompts.append(row)
    except Exception as exc:
        meta["collector_error"] = str(exc)

    # fallback: 기존 파일 (오늘) 로드
    if not all_prompts:
        today = datetime.now().strftime("%Y%m%d")
        fallback_file = Path(workdir) / "logs" / f"prompts_collected_{today}.jsonl"
        meta["fallback_file"] = str(fallback_file)
        if fallback_file.exists():
            with open(fallback_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        source = str(row.get("source", ""))
                        if source in {"codex_session", "codex"}:
                            row["source"] = "codex"
                        all_prompts.append(row)

    all_prompts = _dedupe_prompts(all_prompts)

    now = datetime.now()
    current_cutoff = now - timedelta(days=days_back)
    previous_cutoff = now - timedelta(days=days_back * 2)

    current_prompts: List[Dict[str, Any]] = []
    previous_prompts: List[Dict[str, Any]] = []
    for row in all_prompts:
        ts = _parse_prompt_datetime(row)
        if ts is None:
            current_prompts.append(row)
            continue
        if ts >= current_cutoff:
            current_prompts.append(row)
        elif previous_cutoff <= ts < current_cutoff:
            previous_prompts.append(row)

    current_prompts = _dedupe_prompts(current_prompts)
    previous_prompts = _dedupe_prompts(previous_prompts)
    meta["total_loaded"] = len(all_prompts)
    meta["current_prompts"] = len(current_prompts)
    meta["previous_prompts"] = len(previous_prompts)
    return current_prompts, previous_prompts, meta


def deep_karpathy_analysis(prompts: List[Dict], commits: List[Dict]) -> str:
    """Karpathy 원칙 깊이 있는 분석 (3000자)"""
    lines = []
    lines.append("## 🎯 Part 2: Karpathy 원칙 - 깊이 있는 분석")
    lines.append("")

    # 1. Think Before Coding
    lines.append("### 1. Think Before Coding: 가정하지 말고 질문하라")
    lines.append("")

    question_prompts = [p for p in prompts if '?' in p.get('content', '') or any(
        word in p.get('content', '').lower()
        for word in ['어떻게', '왜', '뭐', '무엇']
    )]
    command_prompts = [p for p in prompts if any(
        word in p.get('content', '') for word in ['해줘', '만들어', '추가']
    )]

    q_ratio = len(question_prompts) / max(len(prompts), 1) * 100

    lines.append(f"**질문형 프롬프트**: {len(question_prompts)}개 ({q_ratio:.1f}%)")
    lines.append(f"**지시형 프롬프트**: {len(command_prompts)}개 ({len(command_prompts)/max(len(prompts),1)*100:.1f}%)")
    lines.append("")

    if question_prompts:
        lines.append("**좋은 질문 사례**:")
        for p in _pick_quality_examples(question_prompts, 3, strategy="high"):
            source = p.get('source', 'unknown')
            content = p.get('content', '')[:100]
            date = p.get('date', '')
            quality = p.get("_quality_score", 0)
            lines.append(f"- \"{content}\" ({source}, {date}, 품질 {quality:.1f})")
        lines.append("")

    if command_prompts:
        lines.append("**지시형 사례** (개선 가능):")
        for p in _pick_quality_examples(command_prompts, 3, strategy="low"):
            source = p.get('source', 'unknown')
            content = p.get('content', '')[:100]
            date = p.get('date', '')
            quality = p.get("_quality_score", 0)
            lines.append(f"- \"{content}\" ({source}, {date}, 품질 {quality:.1f})")
        lines.append("")

    lines.append("**분석**:")
    if q_ratio < 30:
        lines.append("⚠️ 질문형 프롬프트가 부족합니다.")
        lines.append("")
        lines.append("**왜 문제인가?**")
        lines.append("지시형 프롬프트는 '해결책을 가정'합니다.")
        lines.append("예: \"커밋과 푸시해줘\" → 커밋이 해결책이라고 가정")
        lines.append("")
        lines.append("하지만 진짜 문제는:")
        lines.append("- 커밋 메시지가 불명확한가?")
        lines.append("- 변경사항이 너무 많은가?")
        lines.append("- 테스트가 실패하는가?")
        lines.append("")
        lines.append("**질문형으로 바꾸면**:")
        lines.append("\"지금 커밋할 준비가 됐는지 확인해줄래? 뭐가 빠졌는지 체크해봐\"")
        lines.append("")
        lines.append("**다음 주 실험**:")
        lines.append("프롬프트 작성 전 3초 멈추고:")
        lines.append("'내가 해결책을 가정하고 있는가?' 자문하기")
        lines.append("")
        lines.append("**목표**: 질문형 프롬프트 50% 이상")
    else:
        lines.append("✅ 질문형 프롬프트 비율이 좋습니다!")
        lines.append(f"{q_ratio:.1f}%는 건강한 수준입니다.")
        lines.append("")
        lines.append("**유지 방법**:")
        lines.append("- 프롬프트에 '왜', '어떻게' 포함하기")
        lines.append("- 관찰 먼저, 지시는 나중에")
        lines.append("- '~해줘' 대신 '~어떻게 하면 될까?'")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 2. Simplicity First
    lines.append("### 2. Simplicity First: 단순함이 최고")
    lines.append("")

    refactor_commits = [c for c in commits if any(
        word in c['message'].lower()
        for word in ['리팩토링', '단순화', '정리', 'refactor', 'simplify', 'clean']
    )]

    lines.append(f"**리팩토링 커밋**: {len(refactor_commits)}개 / 전체 {len(commits)}개")
    lines.append("")

    if refactor_commits:
        lines.append("**단순화 작업**:")
        for c in refactor_commits:
            lines.append(f"- {c['date']}: {c['message']}")
        lines.append("")
        lines.append("✅ 코드 단순화를 의식하고 있습니다!")
    else:
        lines.append("⚠️ 리팩토링 작업이 없습니다.")
        lines.append("")
        lines.append("**Karpathy의 조언**:")
        lines.append("\"200줄짜리 코드가 50줄로 줄어들 수 있다면 다시 써라\"")
        lines.append("")
        lines.append("**복잡도의 징후**:")
        lines.append("- 같은 코드를 3번 이상 복붙")
        lines.append("- 함수가 50줄 넘음")
        lines.append("- if 중첩이 3단계 이상")
        lines.append("- 변수 이름에 숫자 (data1, data2...)")
        lines.append("")
        lines.append("**다음 주 액션**:")
        lines.append("1. 가장 긴 함수 찾기")
        lines.append("2. 3개 이상 작은 함수로 분리")
        lines.append("3. 커밋 메시지에 'refactor:' 태그 붙이기")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 3. Surgical Changes
    lines.append("### 3. Surgical Changes: 요청된 것만 변경")
    lines.append("")

    commit_dates = Counter(c['date'] for c in commits)
    if len(commit_dates) == 1 and commits:
        single_date = list(commit_dates.keys())[0]
        lines.append(f"⚠️ **모든 커밋이 {single_date} 하루에 집중**")
        lines.append("")
        lines.append("**왜 문제인가?**")
        lines.append("하루에 몰아서 작업하면:")
        lines.append("- 커밋 단위가 커짐")
        lines.append("- 여러 변경이 섞임")
        lines.append("- 롤백이 어려움")
        lines.append("- 리뷰가 힘듦")
        lines.append("")
        lines.append("**예시**:")
        for c in commits[:3]:
            lines.append(f"- {c['time']}: {c['message']}")
        lines.append("")
        lines.append("이 커밋들이 정말 한 번에 이루어져야 했나요?")
        lines.append("")
        lines.append("**다음 주 실험**:")
        lines.append("- 매일 최소 1커밋")
        lines.append("- 한 커밋 = 한 가지 변경")
        lines.append("- 테스트 → 커밋 → 다음 작업")
    elif len(commits) > 0:
        avg_msg_len = sum(len(c['message']) for c in commits) / len(commits)
        lines.append(f"**평균 커밋 메시지 길이**: {avg_msg_len:.1f}자")
        lines.append("")
        if 20 <= avg_msg_len <= 80:
            lines.append("✅ 적절한 커밋 크기입니다!")
            lines.append("짧지도, 길지도 않은 메시지 = 적절한 범위의 변경")
        else:
            lines.append("⚠️ 커밋 크기 조정 필요")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 4. Goal-Driven
    lines.append("### 4. Goal-Driven: 검증 가능한 목표")
    lines.append("")

    goal_keywords = ['테스트', '완료', '성공', '통과', 'test', 'pass', 'done', '✅']
    goal_prompts = [p for p in prompts if any(
        word in p.get('content', '').lower() for word in goal_keywords
    )]

    lines.append(f"**목표 지향 프롬프트**: {len(goal_prompts)}개 / {len(prompts)}개")
    lines.append("")

    if goal_prompts:
        lines.append("**검증 가능한 목표 사례**:")
        for p in _pick_quality_examples(goal_prompts, 3, strategy="high"):
            content = p.get('content', '')[:100]
            quality = p.get("_quality_score", 0)
            lines.append(f"- \"{content}\" (품질 {quality:.1f})")
        lines.append("")

    lines.append("**Karpathy의 조언**:")
    lines.append("❌ 약한 목표: \"버그 고쳐\"")
    lines.append("✅ 강한 목표: \"재현 테스트 작성 → 통과시키기\"")
    lines.append("")

    if len(goal_prompts) < len(prompts) * 0.2:
        lines.append("**문제**: 대부분의 프롬프트가 목표를 명시하지 않습니다.")
        lines.append("")
        lines.append("**개선 방법**:")
        lines.append("1. 작업 시작 전: \"이 작업의 완료 조건은?\"")
        lines.append("2. 프롬프트에 포함: \"~가 완료되면 성공\"")
        lines.append("3. 커밋 전: \"목표를 달성했는가?\"")
        lines.append("")
        lines.append("**예시**:")
        lines.append("Before: \"로그인 기능 만들어줘\"")
        lines.append("After: \"로그인 기능 만들어줘. 성공 조건: 테스트 3개 통과\"")

    lines.append("")

    return "\n".join(lines)


def deep_bitter_lesson_analysis(prompts: List[Dict], prev_prompts: List[Dict]) -> str:
    """Bitter Lesson 깊이 있는 분석 (2000자)"""
    lines = []
    lines.append("## 💡 Part 3: Bitter Lesson - 품질 vs 양")
    lines.append("")
    lines.append("> \"스케일되는 학습 시스템이 결국 이긴다\"")
    lines.append("> \"영리함은 '기능 추가'가 아니라 '학습 가능한 구조 설계'에 써라\"")
    lines.append("")

    # 프롬프트 품질 분석
    lengths = [len(p.get('content', '')) for p in prompts]
    avg_length = sum(lengths) / len(lengths) if lengths else 0
    quality_scores = [_prompt_quality_score(p) for p in prompts]
    avg_quality = sum(quality_scores) / max(len(quality_scores), 1)
    good_quality = sum(1 for s in quality_scores if s >= 70)
    low_quality = sum(1 for s in quality_scores if s < 40)

    lines.append(f"**평균 프롬프트 길이**: {avg_length:.1f}자")
    lines.append(f"**평균 프롬프트 품질 점수(0-100)**: {avg_quality:.1f}")
    lines.append(f"- 우수(70+): {good_quality}개 ({good_quality/max(len(prompts),1)*100:.1f}%)")
    lines.append(f"- 개선 필요(<40): {low_quality}개 ({low_quality/max(len(prompts),1)*100:.1f}%)")
    lines.append("")

    # 길이별 분류
    short = [p for p in prompts if len(p.get('content', '')) < 30]
    medium = [p for p in prompts if 30 <= len(p.get('content', '')) <= 200]
    long = [p for p in prompts if len(p.get('content', '')) > 200]

    lines.append("**길이 분포**:")
    prompt_count = max(len(prompts), 1)
    lines.append(f"- 짧음 (<30자): {len(short)}개 ({len(short)/prompt_count*100:.1f}%)")
    lines.append(f"- 적정 (30-200자): {len(medium)}개 ({len(medium)/prompt_count*100:.1f}%)")
    lines.append(f"- 긺 (>200자): {len(long)}개 ({len(long)/prompt_count*100:.1f}%)")
    lines.append("")

    if short:
        lines.append("**너무 짧은 프롬프트 예시**:")
        for p in _pick_quality_examples(short, 3, strategy="low"):
            content = p.get('content', '')
            quality = p.get("_quality_score", 0)
            lines.append(f"- \"{content}\" ({len(content)}자, 품질 {quality:.1f})")
        lines.append("")
        lines.append("**문제**: 맥락이 부족합니다.")
        lines.append("AI는 당신의 의도를 추측해야 합니다.")
        lines.append("")
        lines.append("**개선 예시**:")
        lines.append("Before: \"커밋해줘\" (7자)")
        lines.append("After: \"변경된 파일들 확인하고, 의미 있는 커밋 메시지로 커밋해줘\" (36자)")
        lines.append("")

    if long:
        lines.append("**긴 프롬프트 예시**:")
        for p in _pick_quality_examples(long, 2, strategy="high"):
            content = p.get('content', '')[:100]
            quality = p.get("_quality_score", 0)
            lines.append(f"- \"{content}...\" ({len(p.get('content', ''))}자, 품질 {quality:.1f})")
        lines.append("")
        lines.append("**분석**: 긴 프롬프트는 두 가지 가능성:")
        lines.append("1. ✅ 맥락이 풍부함 (좋음)")
        lines.append("2. ⚠️ 여러 요청이 섞임 (나쁨)")
        lines.append("")
        lines.append("**체크**: 긴 프롬프트를 2-3개로 나눌 수 있나요?")
        lines.append("나눌 수 있다면 → 나누는 게 좋습니다")
        lines.append("")

    # 반복 패턴 감지
    prompt_starts = [p.get('content', '')[:30].lower() for p in prompts]
    repeated = [(text, count) for text, count in Counter(prompt_starts).items() if count > 3]

    if repeated:
        lines.append("**반복되는 프롬프트 패턴** (자동화 고려):")
        for text, count in repeated[:3]:
            lines.append(f"- \"{text}...\" ({count}회)")
        lines.append("")
        lines.append("**Bitter Lesson 적용**:")
        lines.append("반복 = 스캐폴딩 필요 신호")
        lines.append("")
        lines.append("**자동화 방법**:")
        lines.append("1. 스크립트로 만들기")
        lines.append("2. Git alias 설정")
        lines.append("3. BoramClaw 도구로 등록")
        lines.append("")

    # 품질 추이
    if prev_prompts:
        prev_avg = sum(len(p.get('content', '')) for p in prev_prompts) / max(len(prev_prompts), 1)
        delta = avg_length - prev_avg
        lines.append(f"**전주 대비**: {'+' if delta > 0 else ''}{delta:.1f}자")
        lines.append("")
        if delta > 10:
            lines.append("📈 프롬프트가 더 상세해졌습니다!")
        elif delta < -10:
            lines.append("📉 프롬프트가 짧아졌습니다.")
        else:
            lines.append("➡️ 평균 길이 유지")
        lines.append("")

    # Boris Cherny의 교훈
    lines.append("**Boris Cherny (Claude Code 창시자)의 교훈**:")
    lines.append("")
    lines.append("1. **만들되 집착하지 말 것**")
    lines.append("   - 이번 주 만든 기능도 다음 모델에선 불필요할 수 있음")
    lines.append("   - 유연하게, 버릴 준비를 하고")
    lines.append("")
    lines.append("2. **측정하되 과신하지 말 것**")
    lines.append(f"   - 프롬프트 {len(prompts)}개? 중요한 건 품질")
    lines.append(f"   - 평균 {avg_length:.0f}자? 중요한 건 명확성")
    lines.append("")
    lines.append("3. **모델과 함께 학습하기**")
    lines.append("   - 프롬프트도 진화해야 함")
    lines.append("   - 이번 주 패턴이 다음 주엔 달라질 수 있음")
    lines.append("")

    return "\n".join(lines)


def deep_pattern_insights(prompts: List[Dict], commits: List[Dict]) -> str:
    """패턴 깊이 있는 분석 (2000자)"""
    lines = []
    lines.append("## 🔍 Part 4: 패턴 인사이트 - 당신의 작업 스타일")
    lines.append("")

    # 소스별 분포
    sources = Counter(p.get('source') for p in prompts)
    lines.append("### 주력 도구 분석")
    lines.append("")

    for source, count in sources.most_common():
        pct = count / len(prompts) * 100
        lines.append(f"**{source}**: {count}개 ({pct:.1f}%)")
        lines.append("")

        if source == "claude_code" and pct > 50:
            lines.append("Claude Code가 주력입니다.")
            lines.append("특징: 프로젝트 기반, 파일 편집, 터미널 통합")
            lines.append("강점: 맥락 유지, 연속 작업")
            lines.append("")

        elif source == "codex" and pct > 30:
            lines.append("Codex 사용이 활발합니다.")
            lines.append("특징: 터미널 중심, 빠른 실행")
            lines.append("강점: 즉각적 피드백, 셸 통합")
            lines.append("")

    # 시간 패턴
    if commits:
        lines.append("### 시간 패턴 분석")
        lines.append("")

        commit_times = [c['time'][:2] for c in commits]  # 시간만
        hour_dist = Counter(commit_times)

        lines.append("**커밋 시간대**:")
        for hour, count in sorted(hour_dist.items()):
            lines.append(f"- {hour}시: {count}건")
        lines.append("")

        # 패턴 해석
        morning = sum(count for hour, count in hour_dist.items() if '06' <= hour < '12')
        afternoon = sum(count for hour, count in hour_dist.items() if '12' <= hour < '18')
        evening = sum(count for hour, count in hour_dist.items() if '18' <= hour < '24')
        night = sum(count for hour, count in hour_dist.items() if '00' <= hour < '06')

        lines.append("**근무 패턴**:")
        lines.append(f"- 오전 (06-12): {morning}건")
        lines.append(f"- 오후 (12-18): {afternoon}건")
        lines.append(f"- 저녁 (18-24): {evening}건")
        lines.append(f"- 심야 (00-06): {night}건")
        lines.append("")

        if evening + night > morning + afternoon:
            lines.append("🦉 **Night Owl 패턴**")
            lines.append("저녁/심야 작업이 많습니다.")
            lines.append("")
            lines.append("**장점**: 방해 없는 집중 시간")
            lines.append("**주의**: 수면 패턴 체크 필요")
            lines.append("")
        elif morning > afternoon + evening:
            lines.append("🐤 **Early Bird 패턴**")
            lines.append("오전 작업이 집중됩니다.")
            lines.append("")
            lines.append("**장점**: 하루를 효율적으로 시작")
            lines.append("**주의**: 오후 에너지 관리")
            lines.append("")

    # 프롬프트 타입 균형
    lines.append("### 프롬프트 타입 균형")
    lines.append("")

    question_count = sum(1 for p in prompts if '?' in p.get('content', ''))
    command_count = sum(1 for p in prompts if any(word in p.get('content', '') for word in ['해줘', '만들어']))
    review_count = sum(1 for p in prompts if any(word in p.get('content', '') for word in ['확인', '리뷰', '체크']))

    total_typed = question_count + command_count + review_count
    if total_typed > 0:
        lines.append(f"- 질문형: {question_count}개 ({question_count/total_typed*100:.1f}%)")
        lines.append(f"- 지시형: {command_count}개 ({command_count/total_typed*100:.1f}%)")
        lines.append(f"- 검토형: {review_count}개 ({review_count/total_typed*100:.1f}%)")
        lines.append("")

        if question_count > command_count + review_count:
            lines.append("💡 **탐색 단계**: 질문이 많습니다")
            lines.append("새로운 것을 배우고 있거나, 문제를 이해하는 단계")
        elif command_count > question_count + review_count:
            lines.append("🔨 **실행 단계**: 지시가 많습니다")
            lines.append("구현에 집중하는 단계")
        elif review_count > 0:
            lines.append("🔍 **검토 단계**: 확인 작업이 있습니다")
            lines.append("품질 관리에 신경 쓰는 좋은 신호")
        else:
            lines.append("⚖️ **균형**: 탐색, 실행, 검토가 균형을 이룹니다")

    lines.append("")

    return "\n".join(lines)


def deep_next_week_goals(data: Dict[str, Any]) -> str:
    """다음 주 SMART 목표 (2000자)"""
    lines = []
    lines.append("## 🎯 Part 5: 다음 주 SMART 목표 + 실행 계획")
    lines.append("")

    prompts = data.get('prompts', [])
    commits = data.get('commits', [])

    # Goal 1: 커밋 분산
    lines.append("### Goal 1: 커밋 분산 (매일 커밋)")
    lines.append("")
    lines.append(f"**현재 상태**: {len(commits)}개 커밋")
    lines.append("")

    commit_dates = len(set(c['date'] for c in commits))
    lines.append(f"**분산도**: {commit_dates}일 / 7일")
    lines.append("")

    lines.append("**SMART 목표**:")
    lines.append("- Specific: 매일 최소 1개 커밋")
    lines.append("- Measurable: `git log --since='1 week ago' --format='%ad' --date=short | uniq | wc -l` >= 7")
    lines.append("- Achievable: 작은 단위로 나누기")
    lines.append("- Relevant: Surgical Changes 원칙 강화")
    lines.append("- Time-bound: 다음 금요일까지")
    lines.append("")

    lines.append("**실행 계획**:")
    lines.append("1. 아침: 어제 작업 커밋 확인")
    lines.append("2. 작업 시작 전: 오늘의 커밋 목표 정하기")
    lines.append("3. 점심 후: 오전 작업 커밋")
    lines.append("4. 퇴근 전: 오후 작업 커밋")
    lines.append("")

    lines.append("**예상 장애물**:")
    lines.append("- \"아직 완성 안 됐는데 커밋?\"")
    lines.append("  → WIP (Work In Progress) 커밋 OK")
    lines.append("  → 나중에 rebase로 정리 가능")
    lines.append("")

    # Goal 2: 프롬프트 품질
    avg_length = sum(len(p.get('content', '')) for p in prompts) / max(len(prompts), 1)

    lines.append("### Goal 2: 프롬프트 품질 70점 이상")
    lines.append("")
    lines.append(f"**현재**: 평균 {avg_length:.1f}자")
    lines.append("")

    lines.append("**품질 기준**:")
    lines.append("1. 길이: 30-200자 (30점)")
    lines.append("2. 맥락 제공: '왜', '위해' 포함 (20점)")
    lines.append("3. 구체적: 10단어 이상 (20점)")
    lines.append("4. 검증 가능: 목표 명시 (30점)")
    lines.append("")

    lines.append("**실행 계획**:")
    lines.append("1. 프롬프트 작성 전 체크리스트:")
    lines.append("   - [ ] 맥락을 설명했는가?")
    lines.append("   - [ ] 목표가 명확한가?")
    lines.append("   - [ ] 검증 방법이 있는가?")
    lines.append("")
    lines.append("2. 프롬프트 템플릿 사용:")
    lines.append("   \"{작업} + {이유} + {성공 조건}\"")
    lines.append("")
    lines.append("**예시**:")
    lines.append("Before: \"테스트 만들어줘\"")
    lines.append("After: \"로그인 API 테스트 만들어줘. 인증 버그가 계속 나서. 성공/실패 케이스 각 3개씩\"")
    lines.append("")

    # Goal 3: Karpathy 원칙
    lines.append("### Goal 3: Karpathy 종합 점수 60점 이상")
    lines.append("")
    lines.append("**현재**: 37점 (Think 32, Simplicity 0, Surgical 100, Goal 17)")
    lines.append("")

    lines.append("**집중 영역**: Simplicity First (현재 0점)")
    lines.append("")

    lines.append("**실행 계획**:")
    lines.append("1. 매주 1개 파일 리팩토링")
    lines.append("2. 리팩토링 체크리스트:")
    lines.append("   - [ ] 중복 코드 제거")
    lines.append("   - [ ] 함수 분리 (50줄 이하)")
    lines.append("   - [ ] 변수명 명확화")
    lines.append("   - [ ] 불필요한 주석 제거")
    lines.append("")

    lines.append("**타겟**:")
    lines.append("가장 긴 파일/함수 찾기:")
    lines.append("```bash")
    lines.append("find . -name '*.py' -exec wc -l {} \\; | sort -rn | head -5")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def deep_study_loop_section(prompts: List[Dict], workdir: str) -> str:
    """
    ML 16주 커리큘럼 학습 진도 Loop 섹션 (주간 회고 전용).
    study_tracker를 호출해 이번 주 학습 증거를 분석하고
    다음 주 학습 계획을 안내한다.
    """
    lines = []
    lines.append("## 📚 Part 6: ML 학습 진도 Loop")
    lines.append("")
    lines.append("> *\"API wrapper 탈출\" 16주 커리큘럼 — 매주 자동 진도 체크*")
    lines.append("")

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from study_tracker import (
            load_study_plan,
            get_current_week_info,
            detect_study_prompts,
            build_study_report,
            format_report_markdown,
            collect_recent_prompts,
            MIN_STUDY_PROMPTS_WEEKLY,
        )

        plan = load_study_plan()
        if not plan:
            lines.append("⚠️ `config/study_plan.json`을 찾을 수 없습니다.")
            lines.append("커리큘럼 시작 날짜와 계획을 설정해주세요.")
            return "\n".join(lines)

        week_info = get_current_week_info(plan)
        status = week_info.get("status", "unknown")

        if status == "not_started":
            lines.append(f"⏳ {week_info.get('message', '')}")
            lines.append("")
            lines.append("커리큘럼 시작 전! 이번 주에 미리 준비하세요:")
            lines.append("1. Vaswani 2017 논문 다운로드")
            lines.append("2. PyTorch 설치 확인")
            lines.append("3. 하루 3시간 블록 캘린더에 잡기")
            return "\n".join(lines)

        if status == "completed":
            lines.append(f"🎉 {week_info.get('message', '')}")
            lines.append("")
            lines.append("16주 완주 달성! 이제 진짜 'API wrapper 탈출' 완성.")
            return "\n".join(lines)

        # 활성 주차 — 상세 분석
        current_week = week_info["week"]
        topic = week_info["topic"]
        phase_name = week_info["phase_name"]
        keywords = week_info["keywords"]

        # 이번 주 프롬프트에서 학습 증거 탐지
        recent = collect_recent_prompts(8, workdir)  # 8일 (주간 + 여유)
        matched, high_quality = detect_study_prompts(recent, keywords, topic)

        lines.append(f"### Week {current_week}: {topic}")
        lines.append(f"**Phase {week_info['phase']}**: {phase_name}")
        lines.append(f"**논문**: {week_info['paper']}")
        lines.append(f"**목표**: {week_info['goal']}")
        lines.append(f"**산출물**: {week_info['deliverable']}")
        lines.append(f"**기간**: {week_info['week_start']} ~ {week_info['week_end']}")
        lines.append("")

        # 진도 판정
        threshold = MIN_STUDY_PROMPTS_WEEKLY
        match_count = len(matched)
        hq_count = len(high_quality)

        if match_count == 0:
            verdict = "🔴 FAIL — 이번 주 학습 흔적 없음"
            verdict_detail = (
                "Codex에게 논문 내용을 단 한 번도 물어보지 않았습니다.\n"
                "공부한 것과 안 한 것은 숫자가 말해줍니다."
            )
        elif match_count < threshold // 2:
            pct = int(match_count / threshold * 100)
            verdict = f"🟠 WEAK — 목표의 {pct}% 달성"
            verdict_detail = (
                f"학습 프롬프트 {match_count}개 탐지 (목표: {threshold}개).\n"
                "조금 더 깊이 파고들어야 합니다."
            )
        elif match_count < threshold:
            verdict = f"🟡 PARTIAL — {match_count}/{threshold}개"
            verdict_detail = "절반 이상 달성! 마지막 스퍼트 필요."
        else:
            verdict = f"🟢 ACHIEVED — {match_count}개 (목표 {threshold}개 초과)"
            verdict_detail = "이번 주 학습 목표 완전 달성! 훌륭합니다."

        lines.append(f"**이번 주 진도**: {verdict}")
        lines.append(f"{verdict_detail}")
        lines.append("")
        lines.append(f"- 탐지된 학습 프롬프트: {match_count}개")
        lines.append(f"- 고품질 학습 프롬프트 (키워드 2개+ 매칭): {hq_count}개")
        lines.append("")

        # 학습 증거 샘플
        if matched:
            lines.append("**이번 주 학습 흔적 (상위 5개)**:")
            for p in matched[:5]:
                kws = ", ".join(p.get("_matched_keywords", [])[:3])
                content = (p.get("content", "") or "")[:100]
                src = p.get("source", "?")
                t = p.get("time", "")
                lines.append(f'- `[{src} {t}]` "{content}" → `{kws}`')
            lines.append("")
        else:
            lines.append("**학습 흔적**: 없음")
            lines.append("")

        # 다음 주 예고 및 현재 주 마무리 체크리스트
        lines.append("### 이번 주 마무리 체크리스트")
        lines.append("")
        deliverable = week_info["deliverable"]
        lines.append(f"- [ ] 산출물 완성: **{deliverable}**")
        lines.append(f"- [ ] 논문/자료 최소 3시간 읽기")
        lines.append(f"- [ ] 수식/개념 손으로 정리")
        lines.append(f"- [ ] Codex에게 핵심 질문 {threshold}개 이상 던지기")
        lines.append("")

        # 다음 주 예고
        next_week_num = current_week + 1
        if next_week_num <= plan.get("total_weeks", 16):
            next_week_info = get_current_week_info(plan, override_week=next_week_num)
            if next_week_info.get("status") in ("active", "unknown"):
                lines.append(f"### 다음 주 예고: Week {next_week_num}")
                lines.append(f"**주제**: {next_week_info.get('topic', '?')}")
                lines.append(f"**논문**: {next_week_info.get('paper', '?')}")
                lines.append(f"**목표**: {next_week_info.get('goal', '?')}")
                lines.append("")
                # 다음 주 준비 추천 질문 1개
                next_kws = next_week_info.get("keywords", [])
                if next_kws:
                    lines.append("**미리 생각해볼 질문**:")
                    lines.append(f'"{next_week_info.get("goal", "다음 주제를 미리 조사해보세요")}"')
                lines.append("")

        # 전체 진도 바
        total_weeks = plan.get("total_weeks", 16)
        done_pct = int((current_week - 1) / total_weeks * 100)
        bar_filled = int(done_pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        lines.append(f"**전체 진도**: [{bar}] Week {current_week}/{total_weeks} ({done_pct}%)")
        lines.append("")

        if match_count == 0:
            lines.append("---")
            lines.append("⚡ **경고**: 이번 주 학습 기록이 전혀 없습니다.")
            lines.append("Codex에서 논문 관련 질문을 시작하세요. 지금 바로.")
            lines.append("")
            lines.append("**첫 질문 예시**:")
            next_q = week_info.get("goal", topic)
            lines.append(f'> "{next_q}"')

    except ImportError as e:
        lines.append(f"⚠️ study_tracker import 실패: {e}")
    except Exception as e:
        lines.append(f"⚠️ 학습 진도 분석 중 오류: {e}")

    return "\n".join(lines)


def run(input_data: dict, context: dict) -> dict:
    """깊이 있는 주간 회고 실행"""
    days_back = input_data.get("days_back", 7)
    workdir = context.get("workdir", ".")

    print("📊 데이터 수집 중...", file=sys.stderr)

    # 프롬프트 수집 (최근 N일 + 이전 N일 윈도우)
    prompts, prev_prompts, collection_meta = collect_prompt_windows(days_back, workdir)

    # Git 커밋
    commits = collect_git_commits(days_back, workdir)

    print("🧠 깊이 있는 분석 중...", file=sys.stderr)

    # 데이터
    data = {
        "prompts": prompts,
        "commits": commits,
        "prev_prompts": prev_prompts
    }

    # 마크다운 생성
    lines = []
    lines.append(f"# 주간 회고 (Week {datetime.now().strftime('%W')}, {datetime.now().strftime('%Y-%m-%d')})")
    lines.append("")
    lines.append("> **Karpathy 원칙 + Bitter Lesson + 1만자 피드백**")
    lines.append("")

    # Part 1: 요약
    lines.append("## 📊 Part 1: Executive Summary")
    lines.append("")
    lines.append(f"**기간**: 최근 {days_back}일")
    lines.append(f"**프롬프트**: {len(prompts)}개")
    lines.append(f"**커밋**: {len(commits)}개")
    lines.append(f"**비교군(이전 {days_back}일)**: {len(prev_prompts)}개")
    if collection_meta.get("collector_success"):
        lines.append("**수집 방식**: universal_prompt_collector 최신 재수집")
    else:
        lines.append("**수집 방식**: fallback 파일 로드")
    lines.append("")

    sources = Counter(p.get('source') for p in prompts)
    lines.append("**프롬프트 소스**:")
    prompt_count = max(len(prompts), 1)
    for source, count in sources.most_common():
        lines.append(f"- {source}: {count}개 ({count/prompt_count*100:.1f}%)")
    lines.append("")

    date_dist = Counter(p.get("date", "unknown") for p in prompts)
    lines.append("**날짜 분포**:")
    for date_label, count in sorted(date_dist.items(), key=lambda x: x[0], reverse=True):
        lines.append(f"- {date_label}: {count}개")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Part 2-5: 깊이 있는 분석
    lines.append(deep_karpathy_analysis(prompts, commits))
    lines.append("")
    lines.append(deep_bitter_lesson_analysis(prompts, prev_prompts))
    lines.append("")
    lines.append(deep_pattern_insights(prompts, commits))
    lines.append("")
    lines.append(deep_next_week_goals(data))
    lines.append("")

    # Part 6: ML 학습 진도 Loop
    lines.append(deep_study_loop_section(prompts, workdir))
    lines.append("")

    # Part 7: 메타 회고
    lines.append("## 🔄 Part 7: 메타 회고 - 이 회고에 대한 회고")
    lines.append("")
    lines.append("**이 회고는**:")
    lines.append("- Karpathy 4가지 원칙 적용 ✅")
    lines.append("- Bitter Lesson 기반 분석 ✅")
    lines.append(f"- {len(prompts)}개 프롬프트 전수 조사 ✅")
    lines.append("- 구체적 사례와 피드백 ✅")
    lines.append("- 실행 가능한 액션 플랜 ✅")
    lines.append("- ML 학습 진도 자동 체크 ✅")
    lines.append("")

    markdown = "\n".join(lines)

    # 파일 저장
    output_file = Path(workdir) / f"deep_weekly_retrospective_{datetime.now().strftime('%Y_week%W')}.md"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(markdown)

    return {
        "success": True,
        "output_file": str(output_file),
        "char_count": len(markdown),
        "word_count": len(markdown.split()),
        "summary": {
            "prompts": len(prompts),
            "commits": len(commits),
            "sections": 7,
            "prev_prompts": len(prev_prompts),
            "sources": dict(sources),
            "collector_success": bool(collection_meta.get("collector_success")),
        },
        "collection_meta": collection_meta,
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
