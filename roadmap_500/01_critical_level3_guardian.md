# [Critical] Level 3 Guardian 구현

- 우선순위: Critical
- 현재 상태: 완료
- 요약: 설정 검증기, 포트 충돌 감지, 의존성 사전 점검

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
- [x] `python3 -m unittest tests.test_guardian -v`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'`

## 변경 파일
- `guardian.py`
- `main.py`
- `tests/test_guardian.py`

## 진행 로그
- 2026-02-18: 항목 파일 생성.
- 2026-02-18: Guardian preflight 구현 (설정 검증/포트 충돌 감지/의존성 점검/자동 수정) 및 main 시작 경로 연동.
