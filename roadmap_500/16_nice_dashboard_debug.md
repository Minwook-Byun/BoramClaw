# [Nice-to-have] 메트릭 대시보드 + --debug/--dry-run

- 우선순위: Nice-to-have
- 현재 상태: 완료
- 요약: 운영 관측성과 디버그 경험 개선

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
- [x] `python3 -m unittest tests.test_metrics_dashboard`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'`

## 변경 파일
- `metrics_dashboard.py`
- `main.py`
- `tests/test_metrics_dashboard.py`

## 진행 로그
- 2026-02-18: 항목 파일 생성.
- 2026-02-18: `--dashboard` CLI 및 `/dashboard|/metrics` 명령 추가, 토큰/복구/도구 호출 요약 대시보드 구현.
- 2026-02-18: 대시보드 생성/렌더링 테스트(`tests/test_metrics_dashboard.py`) 추가 및 전체 테스트 통과.
