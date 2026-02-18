# [Important] 테스트 커버리지 확대

- 우선순위: Important
- 현재 상태: 완료
- 요약: E2E 루프/보안 경계/스케줄/권한 테스트 확장

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
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'`

## 변경 파일
- `tests/test_guardian.py`
- `tests/test_tool_only_mode.py`
- `tests/test_watchdog_runner.py`

## 진행 로그
- 2026-02-18: 항목 파일 생성.
- 2026-02-18: Guardian/Tool-only/Watchdog alert 테스트 추가로 전체 테스트 수 44개로 증가.
- 2026-02-18: Runtime commands/main slim/daemon dispatch 테스트 추가로 전체 테스트 88개(1 skip) 통과.
- 2026-02-18: memory vector/scheduler pending/gmail fallback/setup wizard 테스트 추가로 전체 테스트 98개(1 skip) 통과.
