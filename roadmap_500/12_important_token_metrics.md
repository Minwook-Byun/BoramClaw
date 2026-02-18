# [Important] 토큰 사용량 누적 메트릭

- 우선순위: Important
- 현재 상태: 완료
- 요약: 세션/도구별 비용 추적 파일 생성

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
- [x] `python3 -m unittest tests.test_gateway_usage -v`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'`

## 변경 파일
- `gateway.py`
- `main.py`
- `tests/test_gateway_usage.py`

## 진행 로그
- 2026-02-18: 항목 파일 생성.
- 2026-02-18: ask 단위 토큰 사용량(`input/output/requests`) 수집 및 JSONL 누적 기록(`TOKEN_USAGE_FILE`) 추가.
