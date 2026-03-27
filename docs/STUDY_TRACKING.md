# ML Study Tracking System

> **Codex를 위한 handoff 문서**
> 이 파일을 먼저 읽으면 study tracking 관련 코드를 수정/리팩토링할 때 필요한 모든 맥락을 파악할 수 있습니다.

---

## 1. 왜 만들었는가 (동기)

### 문제
BoramClaw에는 일간/주간 회고 시스템이 있다. 그런데 회고가 "개발 활동(커밋, 프롬프트, 브라우저)"만 추적할 뿐, **공부를 했는지**는 전혀 체크하지 않았다.

사용자는 16주 ML 커리큘럼을 시작하기로 했다:
- 하루 3시간 (논문 1h + 블로그/코드 1h + 정리 1h)
- Transformer → Scaling Laws → FlashAttention → ... → AX 아키텍처
- 목표: "API wrapper 탈출" — 모델 내부를 설명하고 self-host 아키텍처를 설계할 수 있는 수준

### 핵심 인사이트
사용자는 **Codex에게 논문 내용을 질문하며 공부**할 예정이다. 즉, 학습 흔적이 Codex 프롬프트 로그에 남는다. BoramClaw가 이미 Codex 프롬프트를 수집하고 있으므로(via `universal_prompt_collector`), 이걸 분석하면 "공부했는지"를 자동으로 탐지할 수 있다.

### 요구사항
- 매일 회고 시: 오늘 이번 주 주제 관련 공부를 했는가? (경고 포함)
- 매주 회고 시: 이번 주 학습 진도 전체 요약 + 다음 주 예고
- 공부 안 했을 때: 구체적인 추천 질문 제시
- 별도 조작 불필요: 회고 실행만 하면 자동으로 체크

---

## 2. 구현 맥락 (기존 시스템과의 관계)

### 기존 시스템 구조 (변경 전)

```
workday_recap.py (v2.1.0)
  ├── Section 1: screenpipe (화면 활동)
  ├── Section 2: git (커밋)
  ├── Section 3: shell (터미널 명령어)
  ├── Section 4: browser (브라우저)
  └── Section 5: prompts (Claude Code, Codex 등) ← universal_prompt_collector 호출

deep_weekly_retrospective.py
  ├── Part 1: Executive Summary
  ├── Part 2: Karpathy 분석 (Think / Simplicity / Surgical / Goal-Driven)
  ├── Part 3: Bitter Lesson
  ├── Part 4: 패턴 인사이트
  ├── Part 5: 다음 주 SMART 목표
  └── Part 6: 메타 회고
```

### 변경 후

```
workday_recap.py (v2.2.0)
  ├── (기존 Section 1-5 동일)
  └── Section 6: ML Study Progress ← study_tracker.run() 호출 (NEW)

deep_weekly_retrospective.py
  ├── (기존 Part 1-5 동일)
  ├── Part 6: ML 학습 진도 Loop ← deep_study_loop_section() (NEW)
  └── Part 7: 메타 회고 (기존 Part 6에서 이동)

config/study_plan.json (NEW)
  └── 16주 커리큘럼 정의 (주차별 주제, 논문, 목표, 산출물, 키워드)

tools/study_tracker.py (NEW)
  └── 진도 추적 핵심 로직
```

### 데이터 흐름

```
Codex 대화 로그
    │
    ▼
universal_prompt_collector.py
    │  logs/prompts_collected_YYYYMMDD.jsonl 생성
    ▼
study_tracker.py
    │  1. config/study_plan.json에서 현재 주차 계산
    │  2. prompts_collected_*.jsonl 에서 키워드 탐지
    │  3. 학습 증거 수집 + 경고 레벨 판정
    ▼
workday_recap.py (일간)
    │  sections["study"] 에 결과 포함
    ▼
daily_retrospective_*.md 출력
```

---

## 3. 구현 내용

### 파일 목록

| 파일 | 역할 | 버전 |
|------|------|------|
| `config/study_plan.json` | 16주 커리큘럼 데이터 | - |
| `tools/study_tracker.py` | 진도 추적 핵심 로직 | 1.0.0 |
| `tools/workday_recap.py` | 일간 회고 (Section 6 추가) | 2.2.0 |
| `tools/deep_weekly_retrospective.py` | 주간 회고 (Part 6 추가) | - |

---

### 3-1. `config/study_plan.json`

**구조:**
```json
{
  "start_date": "2026-02-23",
  "total_weeks": 16,
  "daily_hours": 3,
  "phases": [
    {
      "phase": 1,
      "name": "Transformer 해부",
      "weeks": [
        {
          "week": 1,
          "topic": "Attention 구조",
          "paper": "Attention Is All You Need (Vaswani, 2017)",
          "goal": "Q, K, V는 왜 필요한가?",
          "deliverable": "self-attention 수식 손으로 정리",
          "keywords": ["self-attention", "vaswani", "qkv", ...]
        }
      ]
    }
  ]
}
```

**설계 결정:**
- `start_date`로 자동 주차 계산 (코드 수정 없이 날짜만 바꾸면 됨)
- `keywords`는 탐지 정확도가 핵심. 너무 일반적인 단어(예: "key", "키")는 false positive 발생 → 구체적 구문 위주로 작성
- 4개 Phase, 각 4주 = 총 16주

**커리큘럼 구조:**
```
Phase 1 (1-4주):  Transformer 해부
  Week 1: Attention 구조 (Vaswani 2017)
  Week 2: Scaling Laws (Kaplan 2020)
  Week 3: FlashAttention (Dao 2022)
  Week 4: KV Cache

Phase 2 (5-8주):  학습 & 파인튜닝
  Week 5: LoRA (Hu 2021)
  Week 6: QLoRA (Dettmers 2023)
  Week 7: RLHF / InstructGPT (Ouyang 2022)
  Week 8: Mixture of Experts (Switch Transformer)

Phase 3 (9-12주): Inference & Serving
  Week 9: PagedAttention / vLLM (2023)
  Week 10: DeepSpeed ZeRO (Rajbhandari 2020)
  Week 11: Tensor Parallelism (Megatron-LM)
  Week 12: Cost Modeling (API vs self-host)

Phase 4 (13-16주): 시스템 레벨 사고
  Week 13: RAG (Lewis 2020)
  Week 14: ReAct (Yao 2022)
  Week 15: Tool Use / Toolformer (Schick 2023)
  Week 16: AX Self-host 아키텍처 설계 통합
```

---

### 3-2. `tools/study_tracker.py`

**주요 함수:**

```python
load_study_plan() -> Optional[Dict]
# config/study_plan.json 로드

get_current_week_info(plan, override_week=None) -> Dict
# start_date 기준으로 오늘이 몇 주차인지 계산
# status: "not_started" | "active" | "completed" | "unknown"
# override_week: 테스트용 주차 강제 지정

collect_recent_prompts(days_back, workdir) -> List[Dict]
# logs/prompts_collected_*.jsonl 에서 최근 N일 프롬프트 수집

detect_study_prompts(prompts, keywords, week_topic) -> (matched, high_quality)
# 키워드 매칭으로 학습 관련 프롬프트 탐지
# high_quality: 2개 이상 키워드 매칭 or 내용 50자 이상

build_study_report(mode, week_info, prompts, days_back) -> Dict
# 경고 레벨 판정 + 샘플 프롬프트 + 추천 질문 생성

format_report_markdown(tracking) -> str
# 회고 리포트용 마크다운 섹션 문자열 생성

_build_suggested_questions(topic, keywords, week_info) -> List[str]
# 주제별 Codex 추천 질문 4개 반환 (하드코딩된 질문 사전)
```

**경고 레벨 기준:**

| 레벨 | 조건 | 의미 |
|------|------|------|
| 🔴 CRITICAL | `matched == 0` | 학습 흔적 없음 |
| 🟠 WARNING | `matched < threshold / 2` | 목표의 50% 미만 |
| 🟡 CAUTION | `matched < threshold` | 목표의 50-99% |
| 🟢 GOOD | `matched >= threshold` | 목표 달성 |

**임계값:**
- 일간: `MIN_STUDY_PROMPTS_DAILY = 3`
- 주간: `MIN_STUDY_PROMPTS_WEEKLY = 15`

**CLI 인터페이스 (BoramClaw 툴 컨트랙트 준수):**
```bash
# 스펙 출력
python3 tools/study_tracker.py --tool-spec-json

# 실행 (일간)
python3 tools/study_tracker.py \
  --tool-input-json '{"mode":"daily"}' \
  --tool-context-json '{"workdir":"/Users/boram/BoramClaw"}'

# 특정 주차 테스트
python3 tools/study_tracker.py \
  --tool-input-json '{"mode":"weekly","override_week":3}' \
  --tool-context-json '{"workdir":"/Users/boram/BoramClaw"}'
```

---

### 3-3. `workday_recap.py` 변경 사항

**추가된 import:**
```python
from study_tracker import run as study_tracker_run, format_report_markdown as study_format_md
```

**`run()` 함수에 추가된 Section 6:**
```python
# 6. ML Study Progress
try:
    study_result = study_tracker_run({"mode": mode, "days_back": days}, context)
    if study_result.get("success"):
        tracking = study_result.get("tracking", {})
        report["sections"]["study"] = tracking
        if tracking.get("status") == "active":
            report["sections"]["study"]["_markdown"] = study_format_md(tracking)
except Exception as e:
    report["errors"].append(f"study_tracker 예외: {str(e)}")
```

**`_generate_summary()` 변경:**
```python
if "study" in sections:
    study = sections["study"]
    if study.get("status") == "active":
        # 예: "ML공부 Week1(Attention 구조) 🔴 0개"
        parts.append(f"ML공부 Week{week}({topic}) {warning_lvl} {matched}개")
```

---

### 3-4. `deep_weekly_retrospective.py` 변경 사항

**추가된 함수:** `deep_study_loop_section(prompts, workdir) -> str`

내부적으로 `study_tracker`를 import하여:
1. 현재 주차 정보 표시
2. 이번 주 학습 증거 (matched prompts) 분석
3. 🔴/🟠/🟡/🟢 진도 판정
4. 이번 주 마무리 체크리스트
5. 다음 주 예고 (주제 + 첫 질문)
6. 전체 진도 바: `[████░░░░░░░░░░░░░░░░] Week 1/16 (0%)`

**구조 변경:**
- 기존 Part 6(메타 회고) → Part 7로 이동
- 새 Part 6 = ML 학습 진도 Loop

---

## 4. 알려진 한계 & 설계 Trade-off

### 키워드 기반 탐지의 한계

현재 방식은 단순 문자열 매칭이다. 한계:

1. **False Positive**: "key"처럼 일반 단어가 키워드에 포함되면 비관련 프롬프트가 탐지됨
   → 해결: 구체적 구문(예: "self-attention", "query key value") 위주로 키워드 작성

2. **False Negative**: 한국어로 질문하면 영어 키워드에 안 걸릴 수 있음
   → 해결: 각 주차 keywords에 한국어/영어 둘 다 포함 (현재 적용 중)

3. **맥락 불인식**: "어텐션"이라는 단어가 있어도 논문 공부 맥락이 아닐 수 있음
   → 현재는 감수. 향후 LLM 기반 분류로 개선 가능

### 프롬프트 수집 의존성

`study_tracker`가 `universal_prompt_collector`의 출력 파일(`logs/prompts_collected_*.jsonl`)에 의존한다. 이 파일이 당일 생성되지 않았으면 학습 탐지가 안 된다.

→ `collect_recent_prompts()`에서 `days_back + 1`로 여유분 확보 중

### start_date 고정

`config/study_plan.json`의 `start_date`를 바꾸면 주차가 자동 재계산된다. 코드 수정 불필요.

---

## 5. 향후 구현 필요한 내용 (TODO)

### 우선순위 High

- [ ] **학습 진도 영속성**: 지난 주 학습 여부를 별도 파일에 저장 (`logs/study_progress.jsonl`)
  현재는 매번 프롬프트를 재스캔 → 주간 단위로 "완료/미완료" 기록을 남겨야 함

- [ ] **산출물 체크**: `deliverable`(예: "self-attention 수식 손으로 정리")이 실제로 어딘가에 저장됐는지 확인
  아이디어: `logs/study_deliverables/week{N}_*.md` 파일 존재 여부 체크

- [ ] **Codex 세션 품질 분석**: 단순 키워드 매칭이 아니라 프롬프트 내용의 깊이 측정
  예: 수식 포함 여부, 질문 길이, 후속 질문 수

### 우선순위 Medium

- [ ] **주차 완료 자동 인정**: 해당 주 프롬프트가 threshold를 넘으면 `study_progress.jsonl`에 `"week_N": "completed"` 기록

- [ ] **누적 진도 대시보드**: 지난 N주의 학습 달성률을 한눈에 볼 수 있는 섹션
  예: `Week 1: ✅ | Week 2: ✅ | Week 3: ❌ | Week 4: 진행중`

- [ ] **일간 학습 알림**: 저녁 8시에 오늘 학습 여부를 확인하고, 안 했으면 추천 질문을 Telegram/알림으로 전송

- [ ] **키워드 자동 업데이트**: 사용자가 실제로 공부한 후 "이번 주 핵심 용어"를 스스로 추가할 수 있는 인터페이스

### 우선순위 Low

- [ ] **LLM 기반 학습 탐지**: 키워드 매칭 대신 `claude-haiku`로 프롬프트가 실제 학습 맥락인지 분류
  비용: 약 1000프롬프트 × $0.00025 = $0.25/일 (허용 가능)

- [ ] **학습 타임라인 시각화**: 24시간 타임라인에 `study` 항목 추가 (현재 git/browser/prompts만 있음)

- [ ] **논문 요약 자동 저장**: Codex와 나눈 학습 대화에서 핵심 개념을 추출해 `notes/week{N}_{topic}.md`로 저장

- [ ] **주간 학습 퀴즈**: 주차 마무리 시 해당 주 키워드로 LLM이 퀴즈 생성 → 이해도 확인

---

## 6. Codex를 위한 빠른 시작

### 이 기능을 수정하거나 확장하려면

```
1. 커리큘럼 수정    → config/study_plan.json
2. 탐지 로직 수정   → tools/study_tracker.py : detect_study_prompts()
3. 경고 기준 수정   → tools/study_tracker.py : MIN_STUDY_PROMPTS_DAILY/WEEKLY
4. 추천 질문 추가   → tools/study_tracker.py : _build_suggested_questions()
5. 일간 회고 수정   → tools/workday_recap.py : Section 6 블록
6. 주간 회고 수정   → tools/deep_weekly_retrospective.py : deep_study_loop_section()
```

### 테스트 방법

```bash
# 현재 주차 확인
python3 tools/study_tracker.py \
  --tool-input-json '{"mode":"daily"}' \
  --tool-context-json '{"workdir":"/Users/boram/BoramClaw"}'

# 특정 주차 시뮬레이션 (override_week)
python3 tools/study_tracker.py \
  --tool-input-json '{"mode":"weekly","override_week":5}' \
  --tool-context-json '{"workdir":"/Users/boram/BoramClaw"}'

# 전체 일간 회고 (study 섹션 포함)
python3 tools/workday_recap.py \
  --tool-input-json '{"mode":"daily","scan_all_repos":true}' \
  --tool-context-json '{"workdir":"/Users/boram/BoramClaw"}'
```

### 주의사항

- `study_tracker.py`는 `collect_recent_prompts()`에서 `logs/prompts_collected_*.jsonl`을 직접 읽는다. `universal_prompt_collector`가 먼저 실행돼야 최신 데이터가 있다.
- `workday_recap.py`는 `study_tracker` import 실패 시 `errors` 배열에 추가하고 계속 진행한다. 예외 처리가 되어 있으므로 study_tracker 오류가 전체 회고를 중단시키지 않는다.
- `override_week` 파라미터는 테스트 전용이다. 프로덕션에서는 사용하지 말 것.

---

## 7. 관련 파일 전체 목록

```
BoramClaw/
├── config/
│   └── study_plan.json          ← 커리큘럼 데이터 (여기서 시작)
├── tools/
│   ├── study_tracker.py          ← 핵심 로직
│   ├── workday_recap.py          ← 일간 회고 (Section 6 포함)
│   ├── deep_weekly_retrospective.py  ← 주간 회고 (Part 6 포함)
│   └── universal_prompt_collector.py ← 프롬프트 수집 (의존성)
├── logs/
│   └── prompts_collected_YYYYMMDD.jsonl  ← study_tracker가 읽는 파일
└── docs/
    └── STUDY_TRACKING.md         ← 이 파일
```

---

*최종 업데이트: 2026-02-20*
*구현자: Claude Code (Sonnet 4.6) + 사용자 지시*
