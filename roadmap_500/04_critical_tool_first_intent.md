# [Critical] Tool-first 강제 메커니즘 개선

- 우선순위: Critical
- 현재 상태: 완료
- 요약: 질문 의도 파악 후 선택적 실행, 과잉 반응 방지

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
- [x] `python3 -m unittest tests.test_tool_only_mode -v`
- [x] `python3 -m unittest tests.test_arxiv_intent -v`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'`

## 변경 파일
- `main.py`
- `tests/test_tool_only_mode.py`

## 진행 로그
- 2026-02-18: 항목 파일 생성.
- 2026-02-18: `/tool-only on|off` 모드 추가. 도구 전용 강제(질문 의도와 실행 의도 분리) 경로를 main 루프에 연동.
