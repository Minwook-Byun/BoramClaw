# Insight: 로컬 Tool Calling 구현 방식

## 1) 무엇을 구현했는가
- 모델이 단순 답변만 하는 게 아니라, 필요할 때 로컬 도구를 실제 실행하도록 구성했다.
- 특히 `ls` 같은 시스템 명령을 모델이 `run_shell` 툴로 실행할 수 있다.
- `tools/` 폴더에 있는 커스텀 도구를 모델이 확인하고(`list_custom_tools`), 재로드(`reload_custom_tools`) 후 사용 가능하다.

## 2) 핵심 구조
- `ClaudeChat`: Anthropic Messages API 호출 + `tool_use`/`tool_result` 루프 처리
- `ToolExecutor`: 내장 툴 + 커스텀 툴 실행기
- `ChatLogger`: 대화/툴 실행 이벤트를 JSONL로 누적

파일 기준:
- `main.py` 한 파일에 오케스트레이션 로직이 들어있다.

## 3) Tool Calling 루프 (핵심)
1. 사용자 입력을 모델로 보낸다.
2. 모델 응답에 `tool_use` 블록이 있으면 로컬에서 해당 툴을 실행한다.
3. 실행 결과를 `tool_result`로 다시 모델에 전달한다.
4. 모델이 최종 텍스트를 반환하면 출력한다.

즉, "모델이 지시"하고 "로컬이 실행"하는 왕복 루프다.

## 4) 내장 툴
- `list_files`
- `read_file`
- `write_file`
- `run_shell`
- `run_python`
- `list_custom_tools`
- `reload_custom_tools`

포인트:
- `run_shell`이 있으므로 모델은 `ls -la tools` 같은 명령으로 폴더 상태를 직접 확인할 수 있다.
- `list_custom_tools`는 `tools/`의 파일 목록, 로드된 툴 목록, 로드 에러를 구조화해서 반환한다.

## 5) 커스텀 툴 로딩 방식
- 기본 커스텀 폴더: `tools/` (`CUSTOM_TOOL_DIR`로 변경 가능)
- 로딩 방식: `importlib`로 `tools/*.py`를 동적 import
- 각 파일은 아래 2개를 반드시 제공해야 함:
  - `TOOL_SPEC` (name, description, input_schema)
  - `run(input_data, context)`

예시 파일:
- `tools/echo_tool.py`

## 6) 모델이 tools 폴더를 "스스로 확인"하는 방법
모델 입장에서 가능한 패턴:
1. `run_shell`로 `ls -la tools` 실행
2. `list_custom_tools` 실행으로 로드 상태 확인
3. 필요하면 `reload_custom_tools` 실행
4. 특정 커스텀 툴(`echo_tool` 등) 호출

## 7) 직접 제어용 명령도 추가
- `/tools`: 현재 사용 가능한 도구 목록 출력
- `/tool <name> <json>`: 특정 툴 직접 실행
- `/reload-tools`: 커스텀 툴 재로드

예시:
```text
/tool run_shell {"command":"ls -la tools"}
/tool list_custom_tools {}
/tool echo_tool {"text":"hello","mode":"upper"}
```

## 8) 안전/제약
- `run_shell`에는 일부 위험 토큰 차단(`rm -rf`, `sudo`, `shutdown` 등)이 있다.
- 파일 접근은 `workdir` 기준 경로 제한 체크를 수행한다.
- 로그는 민감정보 마스킹 후 저장한다.

## 9) API vs 로컬 경계
- API가 하는 일: 추론, 어떤 툴을 호출할지 결정
- 로컬이 하는 일: 실제 파일/명령/파이썬 실행
- 검증 방법: `logs/chat_log.jsonl`에서 `tool_call`, `tool_result` 이벤트 유무 확인

## 10) 왜 이렇게 설계했는가
- 모델이 "설명만" 하는 상태를 넘어서, 실제 작업 수행까지 가능하게 하기 위해서다.
- 동시에 `tools/`를 표준 인터페이스로 두어, 도구 추가/수정/교체를 쉽게 만들기 위해서다.

## 11) `ls`는 정확히 어떻게 실행되는가 (상세)

아래 두 경로가 있다.

### A. 사용자가 직접 실행하는 경로
입력 예:
```text
/tool run_shell {"command":"ls -la tools"}
```

실행 흐름:
1. `main()` 루프가 사용자 입력을 받는다. (`main.py:714`)
2. `/tool ...` 형식이면 `parse_tool_command()`로 파싱한다. (`main.py:639`, `main.py:744`)
3. `tools.run_tool("run_shell", {"command":"ls -la tools"})`를 호출한다. (`main.py:747`)
4. `run_tool()`에서 `name == "run_shell"` 분기로 `_tool_run_shell()`을 호출한다. (`main.py:345`)
5. `_tool_run_shell()` 내부에서:
   - 금지 토큰 검사 (`rm -rf`, `sudo` 등) (`main.py:436`)
   - `subprocess.run(["/bin/zsh","-lc", command], cwd=workdir, ...)` 실행 (`main.py:442`)
6. 결과를 `{"exit_code","stdout","stderr"}`로 반환한다. (`main.py:449`)
7. 해당 결과는 `assistant_output`으로 그대로 출력된다. (`main.py:749`)

핵심:
- 이 경로는 **모델 추론 없이** 즉시 로컬 쉘이 실행된다.
- 즉, 완전한 로컬 실행이다.

### B. 모델이 스스로 호출하는 경로 (tool_use)
입력 예:
```text
tools 폴더 내용 확인해줘
```

실행 흐름:
1. 일반 문장이므로 `chat.ask(...)` 호출. (`main.py:754`)
2. API 응답에 `tool_use`가 있으면 반복 루프에서 파싱. (`main.py:573`, `main.py:578`)
3. 모델이 요청한 툴 이름/인자(예: `run_shell`, `ls -la tools`)를 `tool_runner`에 전달. (`main.py:591`)
4. 실제 실행은 A와 동일하게 `_tool_run_shell()`에서 로컬 `subprocess.run`으로 처리. (`main.py:432`)
5. 실행 결과를 `tool_result`로 모델에 재전달. (`main.py:597`)
6. 모델이 최종 자연어 응답 생성.

핵심:
- 결정은 API(모델), 실행은 로컬.
- 즉 "API가 명령을 골라주고 로컬이 실제로 `ls`를 돌리는" 구조다.

### C. 실행 환경/권한
- 셸: `/bin/zsh -lc`
- 실행 디렉터리: `cwd=str(self.workdir)` (`main.py:444`)
- `workdir`는 `TOOL_WORKDIR` 환경변수로 결정 (`main.py:692`)
- 기본 timeout: `TOOL_TIMEOUT_SECONDS` (상한 120초) (`main.py:684`, `main.py:441`)

### D. 왜 `ls`가 tools 폴더를 볼 수 있는가
- `run_shell`은 `command` 문자열을 그대로 쉘에서 실행하기 때문.
- 따라서 `ls -la tools`, `pwd`, `cat tools/echo_tool.py` 같은 조회 명령이 가능.
- 단, 금지 토큰에 걸리는 명령은 차단된다. (`main.py:436`)

### E. 검증 방법 (로그 기반)
- `logs/chat_log.jsonl`에서 아래 이벤트를 본다:
  - `tool_call`
  - `tool_result`
- 해당 이벤트가 찍혔으면 실제 로컬 툴 실행이 일어난 것.
- `assistant_output`만 있고 `tool_call`이 없으면 모델 텍스트 응답만 한 것.

### F. 오해 방지 포인트
- 모델이 "실행했다"고 말해도, 진짜 실행 여부는 로그 이벤트로 확인해야 한다.
- 신뢰 기준은 설명 문장이 아니라 `tool_call/tool_result` 존재다.

## 12) 파일시스템 100% 모드 (레지스트리 캐시 제거)

현재 구조는 하이브리드 캐시보다 단순한 **파일시스템 우선 모드**로 동작한다.

- 핵심 원칙:
  - `tools/*.py`를 호출 시점마다 재스캔하되, 파일이 바뀐 경우에만 재로딩
  - 캐시된 registry 버전으로 라우팅하지 않음
  - 툴 실행 실패 시 재스캔 후 1회 재시도(방어적 동작)
  - 파일이 변하지 않으면 기존 런타임 핸들(객체)을 재사용하여 매번 import하지 않음
  - 파일 목록 수집은 `ls -1 tools` 실행 결과를 우선 사용

- 관련 도구:
  - `list_custom_tools`
  - `tool_registry_status` (이름은 유지하지만 내용은 filesystem 상태)
  - `create_or_update_custom_tool_file`
  - `delete_custom_tool_file`

- tools_schema 캐시/비용 최적화:
  - `tools` 파일로부터 수집한 schema 전체를 매번 API에 넘기지 않고, 사용자 프롬프트 의도에 맞는 부분집합만 선택
  - 선택 결과를 cache key로 저장하여 다음 유사 요청에서 재사용
  - 실행 결과에 `[tool-schema-opt]` 라인으로 추정 절감률(`saved=xx%`)을 출력

- 스케줄 저장 방식:
  - 기존 `tool_name` 외에 `tool_ref`를 함께 저장
  - custom 툴은 `{"kind":"custom_file","file":"tools/xxx.py","tool_name":"xxx","entrypoint":"run"}`
  - 실행 시 이름이 아니라 파일 기준으로 로딩/실행 가능

- 객체 수명주기(쌍 생성/쌍 소멸):
  - 툴 파일에 `create(context)`가 있으면 객체를 생성하고 `obj.run(...)`으로 실행
  - 객체에 `close()`가 있으면 툴 변경/삭제/종료 시 소멸 호출
  - 즉, 툴을 함수뿐 아니라 장기 객체처럼 운용 가능

- 채팅 세션 방어:
  - `tools/*.py` 변화가 감지되면 채팅 히스토리를 재생성
  - 최근 대화 요약(짧은 메모)만 유지해 컨텍스트 꼬임을 줄임

- 경로 보안 방어:
  - `STRICT_WORKDIR_ONLY=1`에서 상위 디렉토리 접근 차단
  - `run_shell`은 상위(`..`) / 절대경로(`/...`) / 셸 메타문자 사용 차단
  - `run_python`은 strict 모드에서 차단
  - Audit hook으로 파일 쓰기/삭제/이동/권한변경이 workdir 밖이면 차단

## 13) 카나리 배포 (Canary Deployment) 상세 정리

### 13.1 정의
- 카나리 배포는 새 버전을 전체에 한 번에 배포하지 않고, **일부 트래픽(또는 일부 작업)** 에 먼저 적용해 품질을 관찰한 뒤 점진적으로 확대하는 배포 전략이다.
- 이름의 유래는 광산의 카나리아(위험 감지)에서 왔다. 즉, 작은 범위에서 먼저 위험 신호를 탐지한다.

### 13.2 왜 필요한가
- 전량 배포는 문제가 생기면 전체 장애로 번진다.
- 카나리는 실패 반경(blast radius)을 줄인다.
- 특히 에이전트/툴 시스템은 외부 API, 파일 I/O, 권한, 스케줄 작업 등 불확실성이 커서 카나리가 매우 유효하다.

### 13.3 어떤 경우에 특히 중요한가
- 툴 자동 개선(자가 수정) 후 바로 운영 반영할 때
- Gmail/결제/파일삭제 등 실수 비용이 큰 툴일 때
- 스케줄러가 자동으로 주기 실행하는 툴일 때
- 테스트 환경과 실환경 데이터 편차가 큰 경우

### 13.4 기본 승격 모델
일반적인 단계:
1. `10%` (카나리 시작)
2. `30%`
3. `60%`
4. `100%` (전량 승격)

각 단계에서 일정 기간 또는 최소 샘플 수를 채운 후 지표를 확인하고 다음 단계로 이동한다.

### 13.5 승격 판단 지표 (최소 세트)
- 오류율(error rate): `is_error == true` 비율
- 타임아웃율(timeout rate): 툴 timeout 발생 비율
- 지연(latency): `p50`, `p95`, `p99`
- 결과 품질 점수(가능하면): 형식 검증 성공률, 후속 재시도율, 사용자 수정률

권장: `최근 N건` + `최근 T분` 두 창(window)을 함께 본다.
- 예: 최근 100건 AND 최근 30분

## 14) 로컬 Watchdog (from scratch)

외부 watchdog API 없이, 로컬 스크립트로 `main.py`(daemon 모드)를 감시/재시작한다.

- 파일: `watchdog_runner.py`
- 대상 실행: `python3 main.py` (`AGENT_MODE=daemon` 기본 주입)
- 동작:
  - 프로세스 비정상 종료(rc != 0) 시 자동 재시작
  - 짧은 시간 내 반복 크래시일 때 지수 백오프
  - 정상 종료(rc == 0) 시 재시작하지 않고 종료
  - `WATCHDOG_STOP_FILE` 생성 시 안전 종료
  - PID를 `WATCHDOG_PID_FILE`에 기록

### 실행
```bash
python3 watchdog_runner.py
```

### 중지
```bash
touch logs/watchdog.stop
```

### 주요 환경변수
- `WATCHDOG_WORKDIR`
- `WATCHDOG_LOG_FILE`
- `WATCHDOG_STOP_FILE`
- `WATCHDOG_PID_FILE`
- `WATCHDOG_RESTART_BACKOFF_SECONDS`
- `WATCHDOG_MAX_BACKOFF_SECONDS`
- `WATCHDOG_MIN_UPTIME_SECONDS`
- `WATCHDOG_MAX_RESTARTS` (`0`이면 무제한)

### 13.6 승격/중단/롤백 규칙 예시
예시 임계값:
- 승격 조건:
  - 오류율 `<= 2%`
  - 타임아웃율 `<= 1%`
  - p95 지연이 기준 버전 대비 `+20%` 이내
- 중단(hold) 조건:
  - 오류율 `2% ~ 5%`
  - 지연 급증, 샘플 부족
- 롤백 조건:
  - 오류율 `> 5%` 또는 치명 오류(권한오류/데이터손상) 1회 이상

치명 오류는 즉시 롤백(단일 이벤트 트리거)로 처리하는 것이 안전하다.

### 13.7 카나리에서 자주 하는 실수
- 샘플 수 부족 상태에서 성급히 승격
- 평균 지연만 보고 tail latency(p95/p99) 미확인
- 전체 지표만 보고 툴별/입력유형별 분리 관찰 미실시
- 롤백은 준비 안 했는데 승격 자동화만 구현
- 스케줄 작업(배치)과 실시간 요청을 같은 기준으로 평가

### 13.8 이 프로젝트에 맞춘 적용 단위
현재 구조에서는 "서비스 트래픽" 대신 "툴 실행 요청"을 분모로 쓰면 된다.

권장 단위:
- 라우팅 키: `tool_name`
- 버전 식별: `tool_name@version_id` (예: 파일 해시 또는 타임스탬프)
- 관찰 이벤트:
  - `tool_call`
  - `tool_result`
  - `tool_error`
  - (추가) `tool_latency_ms`, `tool_version`, `canary_bucket`

### 13.9 현재 코드 기준 설계안 (구현 방향)
필요 컴포넌트:
1. `ToolVersionRegistry`
   - 각 툴의 `stable` 버전과 `canary` 버전을 관리
   - 카나리 비율(예: 0.1) 저장
2. `CanaryRouter`
   - 실행 시 `stable`/`canary` 중 어느 버전을 사용할지 결정
   - 간단히 `hash(request_id) % 100 < canary_percent` 방식 사용 가능
3. `MetricsAggregator`
   - 버전별 성공/실패/지연 집계
4. `PromotionController`
   - 임계값 평가 후 `승격/유지/롤백` 결정

### 13.10 라우팅 전략
- 랜덤 라우팅: 구현 간단, 재현성 낮음
- 해시 라우팅: 같은 키(예: `job_id`, `conversation_id`)는 같은 버전으로 고정 가능
- 툴 특화 라우팅: 고위험 툴은 카나리 비율 낮게 시작(1~5%)

스케줄러 작업은 요청 수가 적으므로 시간 기반 관찰과 수동 승인 단계가 더 안전하다.

### 13.11 롤백 전략
- 소프트 롤백: 카나리 비율 즉시 `0%`
- 하드 롤백: canary 파일/버전 비활성화 + stable로 강제 고정
- 사후 조치:
  - 실패 입력/로그를 `tool_feedback` 저장
  - 자동 개선 루프의 다음 입력 데이터로 활용

### 13.12 자동 개선 루프와 결합하는 법
권장 파이프라인:
1. 실패로그 수집
2. 패치 생성(스테이징 파일)
3. 정적 검증(`py_compile`, 스키마 체크)
4. 리허설 테스트(고정 케이스)
5. 카나리 10% 배포
6. 지표 통과 시 단계 승격
7. 실패 시 자동 롤백 + 원인 기록

즉, "**자가수정 = 카나리 + 자동평가 + 롤백**" 세트로 운영해야 안전하다.

### 13.13 추천 운영 정책 (초기값)
- 고위험 툴(Gmail send/파일 쓰기):
  - 시작 비율: 1~5%
  - 단계: 1 -> 5 -> 20 -> 50 -> 100
- 저위험 툴(조회/포맷 변환):
  - 시작 비율: 10%
  - 단계: 10 -> 30 -> 60 -> 100
- 최소 샘플:
  - 실시간 툴: 단계당 100건 이상
  - 스케줄 툴: 단계당 3~5회 + 시간 간격 관찰

### 13.14 로그 스키마 권장 확장
기존 `chat_log.jsonl`에 아래 필드를 추가하면 분석이 쉬워진다.
- `tool_name`
- `tool_version`
- `route` (`stable` | `canary`)
- `latency_ms`
- `status` (`ok` | `error`)
- `error_type`

예시:
```json
{
  "event": "tool_result",
  "tool_name": "gmail_reply_recommender",
  "tool_version": "20260217_1a2b3c",
  "route": "canary",
  "latency_ms": 842,
  "status": "ok"
}
```

### 13.15 카나리와 A/B 테스트 차이
- 카나리 배포:
  - 목표는 **안전한 릴리스**
  - "문제 없으면 전량 승격"이 목적
- A/B 테스트:
  - 목표는 **실험/최적화**
  - 반드시 하나로 승격하지 않아도 됨

운영 목적이 다르므로 지표 해석과 종료 조건도 다르다.

### 13.16 요약
- 카나리 배포는 새 버전의 위험을 작은 범위에서 먼저 검증하는 안전장치다.
- 에이전트 시스템에서는 특히 툴 자동개선과 결합할 때 필수에 가깝다.
- 실전에서는 "카나리 라우팅 + 명확한 지표 + 즉시 롤백"을 세트로 설계해야 한다.
