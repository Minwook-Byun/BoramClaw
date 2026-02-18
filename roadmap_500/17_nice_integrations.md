# [Nice-to-have] Integration 생태계

- 우선순위: Nice-to-have
- 현재 상태: 완료
- 요약: arXiv/GitHub/Google Calendar + Semantic Snapshot/Telegram/Web UI/On-chain 연동 확장

## 체크리스트
- [x] 설계 확정
- [x] 코드 구현
- [x] 테스트 작성/보강
- [x] 테스트 실행 통과
- [x] implementation_checklist.md 점수 반영

## 완료 기준 (DoD)
- 핵심 요구사항이 코드로 반영되어 재현 가능해야 한다.
- 회귀 테스트가 추가/통과되어야 한다.
- 운영 로그 또는 검증 출력으로 동작을 확인할 수 있어야 한다.

## 검증 명령
- [x] `python3 -m unittest tests.test_integration_intent tests.test_tool_specs tests.test_web_ui_server tests.test_messenger_bridge tests.test_semantic_snapshot_tool tests.test_onchain_wallet_tool`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'`

## 변경 파일
- `tools/github_pr_digest.py`
- `tools/google_calendar_agenda.py`
- `tools/stock_price_watch.py`
- `tools/semantic_web_snapshot.py`
- `tools/onchain_wallet_snapshot.py`
- `tools/telegram_send_message.py`
- `web_ui_server.py`
- `messenger_bridge.py`
- `main.py`
- `runtime_commands.py`
- `tests/test_integration_intent.py`
- `tests/test_tool_specs.py`
- `tests/test_web_ui_server.py`
- `tests/test_messenger_bridge.py`
- `tests/test_semantic_snapshot_tool.py`
- `tests/test_onchain_wallet_tool.py`

## 진행 로그
- 2026-02-18: 항목 파일 생성.
- 2026-02-18: GitHub PR 요약 도구(`github_pr_digest`) 및 Google Calendar agenda 도구(`google_calendar_agenda`) 추가.
- 2026-02-18: 프롬프트 의도 기반 스키마 선택에 GitHub/Calendar 키워드 매칭 추가.
- 2026-02-18: 주식 목표가 추적 도구(`stock_price_watch`) 및 `/schedule-arxiv` 자동 스케줄 명령 추가.
- 2026-02-18: `semantic_web_snapshot` 도구 추가(웹 구조 기반 semantic snapshot).
- 2026-02-18: `onchain_wallet_snapshot` 도구 추가(ETH/BTC 공개 API 기반 잔액/트랜잭션 조회).
- 2026-02-18: `telegram_send_message` 도구 추가 및 `messenger_bridge.py` 텔레그램 브리지(수신→에이전트 처리→응답 전송) 구현.
- 2026-02-18: `web_ui_server.py` 추가 및 `main.py --web-ui` 런타임 연동.
- 2026-02-18: 네트워크 필요 도구를 위한 `TOOL_SPEC.network_access` 지원 추가(`strict_workdir_only` 유지 + 네트워크만 선택적 허용).
