# 개발자의 디지털 트윈을 향한 여정: BoramClaw 개발기

## 🤔 문제의식: "어제 뭐 했지?"

개발자로 일하다 보면 자주 마주하는 질문이 있습니다.

- "저번 주에 뭐 했더라?"
- "이 버그, 전에도 본 것 같은데..."
- "그때 읽었던 논문 링크가 뭐였지?"

우리는 매일 수십 개의 파일을 편집하고, 수백 개의 명령어를 실행하며, 수십 개의 웹 페이지를 읽습니다. 하지만 정작 그 **맥락(context)**은 휘발됩니다. 회고(retrospective)를 쓸 때마다 Git 커밋 히스토리를 뒤지고, 브라우저 히스토리를 검색하며, 기억을 되살리는 데 30분을 써야 합니다.

**"내가 한 일을 기억하고, 맥락을 이해하며, 먼저 말을 걸어주는 비서"** — 이것이 제가 만들고 싶었던 것입니다.

---

## 🧠 이론적 배경: ReAct와 Tool-Use LLM

### ReAct 패턴 (Reasoning + Acting)
BoramClaw는 [Yao et al. (2022)](https://arxiv.org/abs/2210.03629)의 **ReAct(Reasoning and Acting)** 패러다임을 따릅니다.

```
Thought → Action → Observation → Thought → ...
```

전통적인 챗봇은 "추론만" 합니다. 하지만 ReAct 에이전트는:
1. **Thought**: 상황을 분석하고 다음 행동을 계획
2. **Action**: 실제 도구(tool)를 실행 (파일 읽기, 명령 실행, API 호출)
3. **Observation**: 결과를 관찰하고 다음 추론에 반영

이 루프를 통해 에이전트는 단순한 "대화"를 넘어 **실제 작업**을 수행할 수 있습니다.

### Tool-Use in Large Language Models
Claude 3.5 Sonnet과 같은 최신 LLM은 **함수 호출(function calling)** 능력을 내장하고 있습니다. 모델이 추론 과정에서 "이 정보를 얻으려면 X 도구를 써야 한다"고 판단하면, 구조화된 JSON으로 도구 호출 요청을 생성합니다.

BoramClaw는 이를 기반으로:
- **동적 도구 로딩(Dynamic Tool Loading)**: `tools/*.py` 파일을 런타임에 스캔하여 에이전트의 능력을 확장
- **Tool-First 원칙**: 필요한 도구가 없으면 스스로 만들고, 테스트하고, 사용

---

## 🏗️ 아키텍처: 4-Tier Self-Healing과 Observable System

### 1. 핵심 구조

```
┌─────────────────────────────────────┐
│  User Interface                     │
│  CLI / Telegram Bot / MCP Server    │
└──────────┬──────────────────────────┘
           │
┌──────────▼──────────────────────────┐
│  Gateway (RequestQueue)             │
│  Lane-based Serialization           │
└──────────┬──────────────────────────┘
           │
┌──────────▼──────────────────────────┐
│  Agent Core (ReAct Loop)            │
│  Thought → Tool Call → Observation  │
└──────────┬──────────────────────────┘
           │
┌──────────▼──────────────────────────┐
│  Tool Executor                      │
│  Built-in + Custom (tools/*.py)     │
└─────────────────────────────────────┘
```

### 2. 4-Tier Self-Healing 설계

**Level 1 - KeepAlive**:
- 프로세스가 죽으면 무조건 재시작
- PID 추적 및 자동 복구

**Level 2 - Watchdog**:
- Health check (HTTP `/health` endpoint)
- 실패 임계값 초과 시 재시작
- Exponential backoff로 반복 크래시 방지

**Level 3 - Guardian**:
- 시작 전 preflight 검증 (설정 파일, 의존성, 포트 충돌)
- 잘못된 설정을 미리 감지해 시작 실패 방지

**Level 4 - Emergency Recovery**:
- **LLM 기반 자가 진단**: 로그와 에러를 분석해 원인 파악
- **Allowlist 기반 자동 복구**: 안전한 액션만 자동 실행
- 복구 성공률 추적 (`logs/recovery_metrics.jsonl`)

이 4단계 설계로 **99.x% uptime**을 달성하며, 사람의 개입 없이 스스로 회복합니다.

### 3. Observable System 원칙

모든 이벤트는 구조화된 로그(JSONL)로 기록됩니다:
- `tool_call`: 어떤 도구를 호출했는가
- `tool_result`: 실행 결과
- `llm_request`: API 호출 내용
- `llm_response`: 모델 응답

이를 통해:
- **디버깅**: 특정 실행을 정확히 재현 가능
- **감사(Audit)**: 모든 작업의 투명한 추적
- **메트릭**: 성공률, 지연시간, 비용 분석

---

## 📱 최근 구현: Telegram Bot 양방향 통신과 개발 활동 추적

### 1. 문제 상황
초기에는 CLI로만 동작했습니다. 하지만 개발하다가 문득 궁금할 때 — 카페에서, 침대에서, 출퇴근 중에 — 터미널을 열기란 번거롭습니다.

**"모바일로 '오늘 뭐 했어?'라고 물으면 바로 답해주면 좋겠다"**

### 2. 기술 구현

#### Telegram Bot API 양방향 통신
- **Long Polling 방식**: `getUpdates` API로 메시지 수신
- **자연어 명령 파싱**: "오늘 뭐했어?" → `workday_recap(mode="daily")`
- **비동기 응답**: 리포트 생성 후 `sendMessage`로 전송

```python
# telegram_bot_listener.py 핵심 로직
while True:
    updates = get_updates(offset=last_update_id + 1)
    for update in updates:
        text = update["message"]["text"]
        chat_id = update["message"]["chat"]["id"]

        # 자연어 → 구조화된 명령 변환
        command = parse_command(text)
        result = execute_tool(command)

        send_message(chat_id, format_report(result))
```

#### 개발 활동 추적 (Git + Shell + Browser)
- **Git 분석**: 커밋 히스토리, diff, 작업 시간대
- **Shell 히스토리**: `~/.zsh_history` 파싱으로 명령어 패턴 감지
- **Browser 히스토리**: Chrome/Safari SQLite 직접 읽기 (로컬만)

```python
# 일일 리포트 생성 로직
def generate_daily_report():
    commits = parse_git_log(since="today")
    commands = parse_zsh_history(since="today")

    # KST 타임존 처리
    KST = ZoneInfo("Asia/Seoul")
    for commit in commits:
        commit["time"] = commit["timestamp"].astimezone(KST)

    return format_with_insights(commits, commands)
```

#### 주간 리포트와 학습 추천
단순한 "무엇을 했는가"를 넘어, **"어떻게 일했는가"**와 **"무엇을 배워야 하는가"**까지 분석합니다.

```
📊 이번 주 리포트 (2026-02-10 ~ 2026-02-16)

생산성: 🔥 매우 활발
- 총 커밋: 47건
- 일평균: 6.7건
- 코드 변화: +1,247 / -823 (순증 +424줄)

📅 일별 분포:
월: ██████████████ 14건
화: ████████████ 12건
수: ██████ 6건
목: ████████████████ 16건
금: ████████ 8건
토: ████ 4건
일: ██ 2건

🏆 TOP 3 생산성 날:
1. 목요일: 16건 (+340줄)
2. 월요일: 14건 (+280줄)
3. 화요일: 12건 (+190줄)

💡 인사이트:
- 주중 집중력이 높고 주말에는 여유 있게 작업
- 목요일이 가장 생산적 (미팅 적고 집중 시간 확보)
- 리팩토링보다 기능 추가가 많았음

📚 주말 학습 추천:
  • Telegram Bot API 고급 기능
  • React Agent 논문 복습
  • LaneQueue 패턴과 동시성 제어
  • 4-Tier Reliability 아키텍처 심화
```

**학습 추천 로직**:
- 커밋 메시지에서 키워드 추출 (`telegram`, `mcp`, `agent`, `queue`, `guardian`)
- 수정된 파일의 확장자 분석 (`.py`, `.ts`, `.rs`)
- 프로젝트 맥락에 맞는 학습 자료 매칭

---

## 🔧 기술적 도전과 해결

### 1. 타임존 문제
**문제**: 모든 Git 타임스탬프가 UTC로 저장되어 한국 사용자에게는 9시간 차이

**해결**:
```python
from zoneinfo import ZoneInfo
KST = ZoneInfo("Asia/Seoul")

# Git 타임스탬프를 KST로 변환
dt = datetime.fromisoformat(commit["date"]).astimezone(KST)
time_str = dt.strftime("%H:%M")  # "14:23"
```

Python 3.9+의 `zoneinfo`를 사용해 시스템 타임존 데이터베이스를 활용했습니다.

### 2. 리포트 차별화
**문제**: 초기에는 "오늘"과 "이번주" 리포트가 헤더만 다르고 내용이 동일

**해결**:
- **일일 리포트**: 커밋별 타임라인, 파일 변경 상세, 시간대별 활동
- **주간 리포트**: 통계적 요약, 생산성 평가, 패턴 분석, 학습 추천

같은 데이터를 다른 **granularity(입도)**로 제공함으로써 각자의 용도를 명확히 했습니다.

### 3. 환경 변수 로딩
**문제**: 테스트 스크립트가 `.env` 파일을 읽어도 `os.environ`에 반영 안 됨

**해결**:
```python
# 파일에서 읽고 명시적으로 os.environ에 설정
for line in env_file.read_text().split("\n"):
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        token = line.split("=", 1)[1].strip()
        os.environ["TELEGRAM_BOT_TOKEN"] = token  # 명시적 설정
```

`dotenv` 라이브러리 대신 직접 파싱하여 의존성을 줄였습니다.

---

## 🎯 향후 비전: "개발자의 디지털 트윈"

현재 BoramClaw는 **과거의 나를 기억하는 비서**입니다. 하지만 최종 목표는 더 큽니다.

### Observer Layer (관찰 계층)
- **Screen Memory**: [screenpipe](https://github.com/mediar-ai/screenpipe) 연동으로 24/7 화면 캡처 + OCR
  - "3시간 전 본 에러 메시지 찾아줘" → 시각적 기억 검색
- **IDE Activity**: WakaTime API로 프로젝트별/파일별 코딩 시간 추적
- **File System Watcher**: macOS FSEvents로 실시간 파일 변경 감지

### Context Engine (맥락 엔진)
```python
class CurrentContext:
    active_project: str        # 현재 작업 중인 repo
    active_file: str           # 에디터에서 열린 파일
    recent_commits: list       # 오늘의 커밋
    open_browser_tabs: list    # 열린 탭 주제
    upcoming_events: list      # 30분 내 일정
    related_memories: list     # 벡터 검색으로 찾은 관련 과거 기록
```

### Proactive Intelligence (능동적 지능)
"기다리는 비서"가 아니라 **"먼저 말을 거는 비서"**:

| 트리거 | 액션 |
|--------|------|
| 마지막 커밋 후 3시간 경과 | "작업 내용 커밋할까요?" |
| 캘린더 이벤트 15분 전 | 발표 자료 초안 자동 생성 |
| 같은 명령어 3일 연속 입력 | "스크립트로 만들까요?" |
| 오후 3시 + 타이핑 속도 저하 | "휴식 추천" |

### Digital Twin (디지털 트윈)
궁극의 목표:
> "내가 없어도, 나처럼 판단하고, 나처럼 대응하는 에이전트"

- **회의 대리 참석**: 내 작업 맥락을 파악하고, 내 톤으로 진행 상황 보고
- **메일 자동 답장**: 내 과거 메일 스타일 학습 → 초안 작성 → 승인 요청
- **코드 리뷰 대리**: 내 코딩 패턴과 선호를 학습해 PR에 대신 코멘트

---

## 🧪 현재 상태와 테스트 커버리지

**테스트**: 98개 (모두 통과)
**커버된 모듈**:
- Agent Core (ReAct loop, tool calling)
- Gateway (RequestQueue, lane serialization)
- 4-Tier Self-Healing (Guardian, Watchdog, Emergency Recovery)
- Tool Executor (permission gates, sandboxing)
- Memory Store (vector indexing with sqlite-vec)
- Multi-Agent Delegation

**점수**: 402/575 (약 70%)
판정: **핵심 기능 완성, 추가 개선 필요**

---

## 📚 배운 것들

### 1. 신뢰의 경계: API vs 로컬 실행
"모델이 '실행했다'고 말한다고 진짜 실행한 게 아니다"

초기에는 모델의 응답을 신뢰했습니다. 하지만 로그를 보니 `tool_call` 이벤트가 없는 경우가 많았습니다. 이제는:
```python
# 진짜 실행 여부는 로그로 검증
assert "tool_call" in log_events
assert log["tool_name"] == "run_shell"
```

### 2. 도구의 멱등성(Idempotency)
에이전트가 재시도하거나, 실수로 중복 호출해도 안전해야 합니다.
- **조회 도구**: 자연스럽게 멱등
- **변경 도구**: `if not exists` 체크, 트랜잭션, undo 메커니즘 필요

### 3. Observable이 곧 Debuggable
모든 이벤트를 JSONL로 남기면:
- 특정 실행을 정확히 재현 가능
- 실패 패턴을 자동으로 감지 가능
- 메트릭 대시보드를 즉시 구축 가능

**"로그가 곧 데이터베이스"**라는 원칙이 강력했습니다.

### 4. 카나리 배포의 중요성
도구를 자동으로 개선하는 시스템에서는 **점진적 배포**가 필수입니다.
- 10% → 30% → 60% → 100% 단계 승격
- 각 단계에서 오류율, 지연시간, 성공률 검증
- 임계값 초과 시 자동 롤백

"한 번에 전체 배포"는 재앙의 지름길입니다.

---

## 🔗 오픈소스와 차별점

### OpenClaw (145K stars)
- **정체성**: 메시지 허브 (13개 채팅 플랫폼 통합)
- **핵심 가치**: "어디서든 대화"

### BoramClaw
- **정체성**: 개발 비서 (모든 개발 활동 관찰)
- **핵심 가치**: "모든 걸 기억하고, 맥락을 이해"

OpenClaw가 **"통합 받은편지함"**이라면, BoramClaw는 **"개발자의 외장 뇌"**를 지향합니다.

---

## 🎬 마치며

BoramClaw는 여전히 진행 중입니다. 하지만 이미 제 일상에 깊숙이 들어왔습니다.

- 매일 밤 21시, 텔레그램으로 자동 리포트가 도착합니다
- 커밋을 오래 안 하면 슬쩍 알림이 옵니다
- 주말에 무엇을 공부할지 추천받습니다

**"코딩하는 사람을 위한, 코딩하는 비서"**

이 여정에서 배운 것들 — ReAct 패턴, 4-Tier Self-Healing, Observable Systems, Canary Deployment — 은 저에게 소중한 자산이 되었습니다. 그리고 이 모든 것을 기록하고 재현할 수 있는 시스템을 만들면서, **"관찰 가능한 것은 개선 가능하다"**는 원칙을 다시 한번 확인했습니다.

---

**GitHub**: [BoramClaw Repository](#) (비공개, 현재는 개인 프로젝트)
**기술 스택**: Python 3.14, Claude 3.5 Sonnet API, Telegram Bot API, SQLite, pytest
**테스트 커버리지**: 98 tests, 0 failures
**아키텍처**: ReAct + Tool-Use LLM + 4-Tier Self-Healing

---

**#AI #LLM #Agent #ReAct #Python #Telegram #DeveloperTools #Productivity #SelfHealing #AutonomousSystems #개발자도구 #생산성 #AI에이전트**

---

*이 글이 도움이 되었다면, 좋아요와 공유 부탁드립니다!*
*질문이나 피드백은 댓글로 환영합니다. 🙏*
