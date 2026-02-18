# [Critical] 데몬 설치 커맨드 (--install-daemon)

- 우선순위: Critical
- 현재 상태: 완료
- 요약: systemd/LaunchAgent 자동 생성 및 해제

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
- [x] `python3 -m py_compile main.py install_daemon.py`
- [x] `python3 -m unittest tests.test_daemon_dispatch -v`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'`

## 변경 파일
- `main.py`
- `tests/test_daemon_dispatch.py`

## 진행 로그
- 2026-02-18: 항목 파일 생성.
- 2026-02-18: `main.py`에 `--install-daemon`, `--uninstall-daemon`, `--daemon-dry-run` 커맨드 추가.
- 2026-02-18: `handle_daemon_service_command()` 분리로 CLI 분기 로직 테스트 가능화, 데몬 분기 테스트 추가.
