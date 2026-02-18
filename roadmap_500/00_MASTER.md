# BoramClaw 500점 목표 마스터 트래커

기준 점수: 208.1 / 575  
목표 점수: 500 / 575

## 진행 규칙
- 각 항목은 개별 파일에서 상태를 관리한다.
- 상태 표기: `미시작` / `진행중` / `완료` / `보류`
- 완료 조건(DoD) + 검증 명령(TDD/스모크)을 반드시 채운다.
- 완료 시 `implementation_checklist.md` 점수 반영 로그를 남긴다.

## 전체 항목 링크
- [01 Critical - Level 3 Guardian](./01_critical_level3_guardian.md)
- [02 Critical - Level 4 Emergency Recovery](./02_critical_level4_emergency_recovery.md)
- [03 Critical - Gateway 분리 완성](./03_critical_gateway_split.md)
- [04 Critical - Tool-first 의도 파악](./04_critical_tool_first_intent.md)
- [05 Critical - 데몬 설치 커맨드](./05_critical_install_daemon.md)
- [06 Critical - /health 검증 및 보완](./06_critical_health_endpoint.md)
- [07 Critical - 로그 로테이션 실제 연동](./07_critical_log_rotation_integration.md)
- [08 Critical - 네트워크 샌드박스](./08_critical_network_sandbox.md)
- [09 Important - Persistent Memory](./09_important_persistent_memory.md)
- [10 Important - Permission System 고도화](./10_important_permission_system.md)
- [11 Important - API Key 암호화 저장](./11_important_api_key_encryption.md)
- [12 Important - 토큰 비용 메트릭](./12_important_token_metrics.md)
- [13 Important - Error Handling 강화](./13_important_error_handling.md)
- [14 Important - 테스트 커버리지 확대](./14_important_test_coverage.md)
- [15 Nice - 패키지형 CLI](./15_nice_cli_packaging.md)
- [16 Nice - 대시보드 + debug/dry-run](./16_nice_dashboard_debug.md)
- [17 Nice - Integration 생태계](./17_nice_integrations.md)
- [18 Bonus - Multi-Agent](./18_bonus_multi_agent.md)
- [19 Bonus - Reflexion/Self-Improvement 통합](./19_bonus_reflexion.md)
- [20 Bonus - main.py 경량화](./20_bonus_main_py_slim.md)

## 현재 스냅샷
| 번호 | 항목 | 우선순위 | 상태 |
|---|---|---|---|
| 01 | Level 3 Guardian | Critical | 완료 |
| 02 | Level 4 Emergency Recovery | Critical | 완료 |
| 03 | Gateway 분리 완성 | Critical | 완료 |
| 04 | Tool-first 의도 파악 | Critical | 완료 |
| 05 | 데몬 설치 커맨드 | Critical | 완료 |
| 06 | /health 검증 및 보완 | Critical | 완료 |
| 07 | 로그 로테이션 실제 연동 | Critical | 완료 |
| 08 | 네트워크 샌드박스 | Critical | 완료 |
| 09 | Persistent Memory | Important | 완료 |
| 10 | Permission System 고도화 | Important | 완료 |
| 11 | API Key 암호화 저장 | Important | 완료 |
| 12 | 토큰 비용 메트릭 | Important | 완료 |
| 13 | Error Handling 강화 | Important | 완료 |
| 14 | 테스트 커버리지 확대 | Important | 완료 |
| 15 | 패키지형 CLI | Nice | 완료 |
| 16 | 대시보드 + debug/dry-run | Nice | 완료 |
| 17 | Integration 생태계 | Nice | 완료 |
| 18 | Multi-Agent | Bonus | 완료 |
| 19 | Reflexion/Self-Improvement 통합 | Bonus | 완료 |
| 20 | main.py 경량화 | Bonus | 완료 |

## 이번 사이클 우선 구현 순서
1. 1~20 항목 1차 구현 완료
2. 통합 E2E 운영 검증 고도화
3. 점수 500+를 위한 고급 항목(웹 스냅샷/벡터DB/설치 위저드) 추가

## 진행 로그
- 2026-02-18: 항목별 md 트래킹 체계 초기 생성.
- 2026-02-18: 01(Level 3 Guardian) 구현 완료. `guardian.py` 추가 및 `main.py` preflight 연동, `tests/test_guardian.py` 통과.
- 2026-02-18: 02(Level 4)의 실패 알림 채널 추가. `WATCHDOG_ALERT_FILE` + `_emit_alert()` + 테스트 추가.
- 2026-02-18: 03(Gateway 분리) 진행. `main.py` 내 미사용 `ClaudeChat` 중복 구현 제거(게이트웨이 단일화 방향).
- 2026-02-18: 04(Tool-first) 진행. `/tool-only on|off` 모드 추가.
- 2026-02-18: 05(데몬 설치 커맨드) 진행. `main.py`에 `--install-daemon/--uninstall-daemon` 추가.
- 2026-02-18: 06(/health) 완료. 헬스 엔드포인트 응답/404 테스트 추가.
- 2026-02-18: 07(로그 로테이션 연동) 완료. Rotating logger 경로 및 테스트 확인.
- 2026-02-18: 08(네트워크 샌드박스) 진행. strict 모드 네트워크 명령/소켓 연결 차단 추가.
- 2026-02-18: 12(토큰 메트릭) 진행. ask 단위 토큰/요청 수 및 비용 추정치를 JSONL로 누적 기록.
- 2026-02-18: 13(에러 핸들링) 진행. Gateway API retry/backoff 및 연결오류 재시도 추가.
- 2026-02-18: 15(CLI 패키징) 진행. `pyproject.toml` 및 `boramclaw` 엔트리포인트 추가.
- 2026-02-18: 10(Permission System) 진행. 런타임 권한 조회/수정 명령(`/permissions`, `/set-permission`) 추가.
- 2026-02-18: 09(Persistent Memory) 진행. 장기 메모리 저장/질의 엔진 및 `/memory` 명령 추가.
- 2026-02-18: 11(API Key) 진행. keychain 우선 + dotenv 평문 opt-in 정책 적용.
- 2026-02-18: 16(대시보드) 완료. `metrics_dashboard.py` 추가, `--dashboard`/`/dashboard` 연동.
- 2026-02-18: 17(Integration) 완료. `github_pr_digest`, `google_calendar_agenda` 도구 추가 및 의도 매칭 확장.
- 2026-02-18: 18(Multi-Agent) 완료. `multi_agent.py` 추가, `/delegate` 및 자동 위임(`MULTI_AGENT_AUTO_ROUTE`) 연동.
- 2026-02-18: 19(Reflexion) 완료. `reflexion_store.py` + `/feedback` + `/reflexion` + self-heal 피드백 파일 누적 연동.
- 2026-02-18: 05(데몬 설치 커맨드) 완료. `handle_daemon_service_command()` 분리 및 `tests/test_daemon_dispatch.py` 추가.
- 2026-02-18: 20(main.py 경량화) 진행. 파서/출력 유틸을 `runtime_commands.py`로 분리(374 LOC 추출).
- 2026-02-18: 02(Level 4 Emergency Recovery) 완료 처리. checklist 반영 동기화.
- 2026-02-18: 03/04/06/07/08/09/10/11/12/13/14/15/20 상태를 완료로 승격. 관련 체크리스트/검증 명령 동기화.
- 2026-02-18: 전체 roadmap 1~20 상태 `완료` 달성.
- 2026-02-18: 추가 고도화(미완 항목 보완): sqlite 벡터 메모리, heartbeat pending task 실행, Gmail IMAP fallback, setup wizard, stock 추적 도구, `/schedule-arxiv` 명령.
