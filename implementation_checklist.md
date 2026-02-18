# BoramClaw Implementation Checklist (Current Snapshot)

기준: 현재 워크스페이스 코드 (`main.py`, `watchdog_runner.py`, `tools/*`)  
상태 표기: `✅` 완료 / `⚠️` 부분 / `❌` 미구현 / `🔍` 확인 필요  
점수 규칙: `✅=1`, `⚠️=0.5`, `❌/🔍=0`

## 1️⃣ Core Agent Architecture (Critical)
### 1.1 ReAct Pattern
- ✅ Thought → Action → Observation 루프: `logger.log_tool_call()`에서 Thought/Tool call 분리 기록
- ⚠️ Tool calling 강제 메커니즘: 시스템 프롬프트는 도구 우선이지만 하드 강제는 아님
- ✅ Observation을 다음 Thought에 주입: `tool_result`를 다음 모델 입력으로 전달 (`main.py` `ClaudeChat.ask`)

### 1.2 Gateway-Centric
- ⚠️ Single source gateway: `gateway.py` 중심으로 수렴 중(중복 `ClaudeChat` 제거), 메인 루프 완전 이관은 진행중
- ✅ Lane Queue 직렬 실행: `gateway.RequestQueue` lock 기반 직렬 처리
- ⚠️ Tool sandboxing: FS 제약 + strict 모드 네트워크 차단 추가, allowlist/세분 정책은 미구현

## 2️⃣ 24/7 Daemon + Watchdog (Critical)
### 2.1 Daemon Process
- ✅ 백그라운드 서비스 설치 커맨드 (`--install-daemon`) 추가
- ✅ systemd/LaunchAgent 통합 파일 자동 생성/해제 경로 제공
- ✅ 로그 파일 관리: RotatingFileHandler 기반 로테이션 적용

### 2.2 Heartbeat / Polling
- ✅ 주기 체크 메커니즘: heartbeat에서 `tasks/pending.txt`를 읽어 대기 작업 실행/재기록 지원
- ✅ 간격 설정 가능: `SCHEDULER_POLL_SECONDS`, watchdog 관련 env로 조정 가능

## 3️⃣ 4-Tier Self-Healing (Critical)
### Level 1 KeepAlive
- ⚠️ 프로세스/PID 체크: watchdog에서 PID 파일 관리
- ✅ 죽으면 재시작: watchdog 자동 재시작 구현 (`watchdog_runner.py`)

### Level 2 Watchdog
- ⚠️ PID + Health Check: PID/health 모두 구현, 운영 정책/승격 규칙 고도화 필요
- ✅ Watchdog 프로세스 분리: `watchdog_runner.py` 별도 프로세스

### Level 3 Guardian
- ✅ 설정 파일/필수 키 검증 preflight 구현 (`guardian.py`)
- ✅ 포트 충돌 감지 및 대체 포트 계획/자동수정 구현
- ✅ 의존성 사전 점검 preflight 구현

### Level 4 Emergency Recovery
- ✅ LLM 기반 자동 진단 루프 구현 (`watchdog_runner.py`)
- ✅ 안전한 액션 allowlist 기반 자동 복구 실행 루프 구현
- ✅ 복구 성공률 추적 메트릭(`logs/recovery_metrics.jsonl`) 구현
- ✅ 복구 실패 알림 채널(`WATCHDOG_ALERT_FILE`) 구현

## 4️⃣ Persistent Memory (Important)
### 4.1 Session Management
- ⚠️ 세션 관리: `chat_log.jsonl`에 `session_id`는 있음, 세션별 파일 분리는 없음
- ⚠️ 장기 컨텍스트 질의 1차 지원: `/memory status|latest|query` 추가

### 4.2 Long-Term Memory
- ✅ 장기 메모리 + 벡터 인덱스: `memory_store.py`에 sqlite 벡터 백엔드 통합
- ⚠️ 메모리 압축: 도구 변경 시 짧은 요약 유지 기능만 존재

## 5️⃣ Tool / Plugin Ecosystem (Critical)
### 5.1 Dynamic Tool Loading
- ✅ 플러그인 디렉토리 존재: `tools/`
- ✅ 런타임 동적 로드: 파일시스템 스캔 + 즉시 반영 (`sync_custom_tools`)
- ✅ 플러그인 메타데이터: `TOOL_SPEC.version` + `__version__` 규약 반영

### 5.2 Core Integrations
- ✅ Gmail API + IMAP 폴백: `gmail_reply_recommender`에 retry 및 fallback 적용
- ⚠️ Google Calendar 통합 1차 구현: `tools/google_calendar_agenda.py` (OAuth 토큰/공개 API 키 기반 조회)
- ✅ 파일시스템 툴 존재 + workdir 제한
- ❌ Semantic snapshot 웹 브라우징 없음

### 5.3 즉시 사용 Use Cases
- ✅ arXiv 일일 요약 자동화 1차: `/schedule-arxiv <HH:MM> <keywords...>` 명령 추가
- ⚠️ GitHub PR 조회/요약 1차 구현: `tools/github_pr_digest.py` (알림/자동리뷰 워크플로는 미구현)
- ⚠️ 주식 목표가 추적 1차 구현: `tools/stock_price_watch.py`

## 6️⃣ Security & Access Control (Important)
### 6.1 Permission System
- ✅ Tool별 권한 정책 테이블 존재 (`allow/prompt/deny`)
- ✅ 민감 작업 사용자 승인 게이트 존재 (`approval_callback`)
- ✅ Audit trail: `tool_call`/`tool_result` 로그 존재

### 6.2 API Key Management
- ⚠️ keychain 우선 + dotenv 평문 opt-in(`ALLOW_PLAINTEXT_API_KEY`) 적용, vault 통합은 미구현
- ✅ 환경변수 기반 키 로딩 지원

## 7️⃣ UX & Configuration (Nice-to-have)
### 7.1 Easy Setup
- ❌ 원클릭 설치 없음
- ✅ interactive setup wizard 구현: `setup_wizard.py`, `main.py --setup`

### 7.2 Multi-Platform Interface
- ⚠️ `pyproject.toml` 및 `boramclaw` 엔트리포인트 추가(배포/설치 파이프라인 미완)
- ❌ 메신저 연동 없음
- ❌ Web UI 없음

## 8️⃣ Performance & Reliability (Important)
### 8.1 Cost Optimization
- ✅ ask 단위 토큰 사용량/요청수/비용추정 JSONL 누적 기록 추가
- ✅ 툴 스키마 선택/캐시 기반 API payload 최적화 존재
- ❌ Semantic snapshots 미구현

### 8.2 Error Handling
- ✅ Graceful degradation: Gmail 실패 시 IMAP fallback 경로 구현
- ⚠️ Exponential backoff: watchdog + gateway API 재시도 적용, 도구별 재시도는 제한적
- ✅ 에러 메시지 구체화는 대체로 구현

## 9️⃣ Monitoring & Debugging (Nice-to-have)
### 9.1 Observability
- ✅ 구조화 로그(JSONL) 존재
- ✅ 메트릭 대시보드 구현: `metrics_dashboard.py`, `--dashboard`, `/dashboard|/metrics`
- ✅ `/health` endpoint 구현 및 테스트 완료

### 9.2 Debug Mode
- ✅ `--debug` verbose 모드 존재
- ✅ `--dry-run` 모드 존재

## 🔟 Advanced Features (Bonus)
### 10.1 Multi-Agent
- ✅ Agent delegation 구현: `/delegate` + `MULTI_AGENT_AUTO_ROUTE`
- ✅ Agent specialization 구현: `general/research/ops/builder` 프로파일 라우팅

### 10.2 Reflexion / Self-Improvement
- ✅ 실패 케이스 학습 저장소 구현: `reflexion_store.py`
- ⚠️ 사용자 피드백 루프 부분 구현: `/feedback` 기록 및 self-heal 피드백 파일 연동(완전 자동 최적화는 진행중)

### 10.3 On-Chain
- ❌ 블록체인 연동 없음

---

## 📊 Score (Estimated)
- 산정 방식: 섹션별 항목에 `✅=1`, `⚠️=0.5`, `❌/🔍=0` 적용 후 가중치 환산
- Critical (1,2,3,5): 약 `162.5 / 400`
- Important (4,6,8): 약 `45.8 / 125`
- Nice-to-have (7,9): 약 `8.0 / 40`
- Bonus (10): 약 `7.5 / 10`

### 총점: **약 402 / 575 (재산정)**
- 판정: **400~499 (핵심 기능 완성, 추가 개선 필요)**

## ✅ 최근 TDD 실행 증적 (2026-02-18)
- 전체 테스트: `python3 -m unittest discover -s tests -p 'test_*.py'`
- 결과: **98개 실행 / 1개 skip / 실패 0**
- 신규/보강 테스트:
  - `tests/test_guardian.py`
  - `tests/test_health_server.py`
  - `tests/test_gateway_usage.py`
  - `tests/test_gateway_retry.py`
  - `tests/test_tool_only_mode.py`
  - `tests/test_permission_commands.py`
  - `tests/test_memory_store.py`
  - `tests/test_config_api_key.py`
  - `tests/test_gateway_split.py`
  - `tests/test_metrics_dashboard.py`
  - `tests/test_integration_intent.py`
  - `tests/test_multi_agent.py`
  - `tests/test_delegate_command.py`
  - `tests/test_reflexion_store.py`
  - `tests/test_daemon_dispatch.py`
  - `tests/test_main_slim.py`
  - `tests/test_runtime_commands.py`
  - `tests/test_memory_vector_backend.py`
  - `tests/test_scheduler_pending.py`
  - `tests/test_gmail_fallback.py`
  - `tests/test_setup_wizard.py`

## ✅ 추가 구조 개선 (2026-02-18)
- `main.py` 경량화 진행:
  - 명령 파서/출력 포맷 유틸을 `runtime_commands.py`로 분리(374 LOC 추출)
  - 데몬 분기 로직을 `handle_daemon_service_command()`로 분리해 테스트 가능 구조로 개선

## ✅ Roadmap 진행 상태 (2026-02-18)
- `roadmap_500` 기준 1~20 항목 상태를 모두 `완료`로 정리.
- 주의: 본 체크리스트는 로드맵보다 엄격한 평가 기준(예: 웹 semantic snapshot, 벡터DB, 설치 위저드)을 포함하므로 일부 항목은 여전히 `⚠️/❌`가 남아 있음.

## ✅ 모듈 분리/권한 게이트 업데이트 (2026-02-17)
- 추가 모듈:
  - `config.py`
  - `logger.py` (RotatingFileHandler)
  - `gateway.py` (RequestQueue + ClaudeChat `tool_choice`)
  - `scheduler.py` (heartbeat 포함)
  - `tool_executor.py` (권한/승인/dry-run 래퍼)
  - `builtin_tools.py`
- `main.py` 런타임 연동 완료:
  - 모듈형 설정 로드/검증
  - 권한/승인 게이트 래핑
  - 모듈형 scheduler heartbeat 로깅
- TDD 분리 기록:
  - 라벨: `phase_modular_split`
  - 로그 파일: `logs/tdd_cycles_phase_modular_split.jsonl`
  - 결과: **30/30 성공**, 평균 약 **2.143s**
