# 일일 개발 활동 리포트 자동화 설정

## 개요

BoramClaw의 "Developer's Digital Twin" 기능 중 Phase 2가 구현되었습니다:

- **Screen Activity** (screenpipe): 화면 OCR 데이터 검색
- **Git Activity**: 커밋 이력 분석
- **Shell Activity**: 명령어 패턴 분석
- **Browser Activity**: 웹 브라우징 이력 분석

이 4가지 데이터를 통합하여 매일 21:00에 자동으로 리포트를 생성하고 macOS 알림을 받을 수 있습니다.

## 사용 가능한 명령어

### 1. 즉시 리포트 생성

#### `/today` - 오늘 활동 리포트
```
/today
```

키워드로 필터링:
```
/today BoramClaw
```

#### `/week` - 주간 활동 리포트
```
/week
```

키워드로 필터링:
```
/week Claude
```

### 2. 직접 툴 호출

workday_recap 툴을 직접 호출:
```
/tool workday_recap {"mode":"daily"}
/tool workday_recap {"mode":"weekly"}
/tool workday_recap {"mode":"daily","focus_keyword":"Python"}
```

daily_recap_notifier 툴 (파일 저장 + 알림):
```
/tool daily_recap_notifier {}
/tool daily_recap_notifier {"notify":false}
/tool daily_recap_notifier {"output_dir":"logs/my_reports"}
```

## 자동 스케줄 등록

### 방법 1: BoramClaw 인터랙티브 모드에서 등록

```bash
python3 main.py
```

그리고 다음 명령어 입력:

```
/tool schedule_daily_tool {
  "tool_name": "daily_recap_notifier",
  "time": "21:00",
  "tool_input": {},
  "description": "Daily developer activity recap"
}
```

### 방법 2: 직접 JSON 파일 편집

`schedules/jobs.json` 파일에 다음 내용 추가:

```json
{
  "jobs": [
    {
      "id": "daily_recap_21",
      "tool_name": "daily_recap_notifier",
      "schedule": "daily",
      "time": "21:00",
      "tool_input": {},
      "description": "Daily developer activity recap",
      "enabled": true
    }
  ]
}
```

### 방법 3: 커스텀 시간 지정

오전 9시에 전날 활동 리포트:
```
/tool schedule_daily_tool {
  "tool_name": "daily_recap_notifier",
  "time": "09:00",
  "tool_input": {},
  "description": "Yesterday's activity recap"
}
```

## 스케줄 관리

### 스케줄 목록 확인
```
/schedules
```

### 스케줄 수동 실행 (테스트용)
```
/run-due-jobs
```

## 생성된 파일 위치

- 일일 리포트: `logs/summaries/daily/YYYY-MM-DD.json`
- 예시: `logs/summaries/daily/2026-02-18.json`

## 리포트 내용

각 리포트는 다음 정보를 포함합니다:

### Shell Activity
- 총 명령어 실행 수
- 유니크 명령어 수
- 자주 사용한 명령어 Top 10
- Alias 추천 (반복되는 긴 명령어)

### Browser Activity
- 총 웹 페이지 방문 수
- 유니크 도메인 수
- 자주 방문한 도메인 Top 10
- 세션 수 (30분 gap 기준)

### Git Activity (git 저장소에서만)
- 커밋 수
- 작성자 목록
- 파일 변경 통계 (추가/삭제 라인)
- 활성 브랜치

### Screen Activity (focus_keyword 지정 시)
- 캡처된 화면 수
- 자주 사용한 앱 Top 5
- 검색된 키워드

## 알림 설정

macOS 시스템 설정에서 알림 권한을 허용해야 합니다:

1. **시스템 설정** → **알림**
2. **스크립트 편집기** 또는 **Terminal** 앱 찾기
3. 알림 허용

## Troubleshooting

### screenpipe가 실행되지 않는 경우

```bash
# 상태 확인
curl http://localhost:3030/health

# 실행
screenpipe --disable-audio --fps 0.2 --port 3030
```

### 리포트가 비어있는 경우

- Git 저장소가 아니면 git 섹션은 비어있습니다
- focus_keyword 없이 실행하면 screen 섹션은 생략됩니다
- Shell history가 비어있으면 shell 섹션도 비어있습니다

### 스케줄이 실행되지 않는 경우

1. BoramClaw가 데몬 모드로 실행 중인지 확인:
   ```bash
   AGENT_MODE=daemon python3 main.py
   # 또는
   python3 watchdog_runner.py
   ```

2. `SCHEDULER_ENABLED=1`이 `.env`에 설정되어 있는지 확인

3. 스케줄 파일 권한 확인:
   ```bash
   ls -la schedules/jobs.json
   ```

## 다음 단계 (Phase 3-5)

- **Phase 3**: MCP Server 구현 → Claude Desktop 통합
- **Phase 4**: Context Engine → 전체 맥락 통합
- **Phase 5**: Rules Engine → 자동 규칙 기반 액션

## 참고 자료

- [CLAUDE.md](CLAUDE.md) - 프로젝트 전체 가이드
- [curious-forging-reddy.md](~/.claude/plans/curious-forging-reddy.md) - 5-Layer Architecture 설계 문서
