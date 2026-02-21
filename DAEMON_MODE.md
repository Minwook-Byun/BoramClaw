# BoramClaw Daemon Mode - 24/7 자동 실행 가이드

## 개요

**Daemon Mode**는 BoramClaw를 백그라운드에서 24/7 실행하여 자동으로 규칙을 평가하고 액션을 실행하는 모드입니다.

## 핵심 기능

### 1. Rules Engine 자동 평가

**주기**: `config/rules.yaml`의 `check_interval` 설정 (기본: 300초 = 5분)

**동작**:
- Scheduler의 heartbeat마다 `rules_engine.evaluate_rules()` 호출
- 조건에 맞는 규칙 자동 실행
- 결과를 `logs/chat_log.jsonl`에 기록

### 2. 자동 알림

**규칙 예시**:
```yaml
# 3시간 코딩 후 커밋 없으면 알림
- name: no_commit_reminder
  trigger:
    conditions:
      - field: session.duration_minutes
        operator: greater_than
        value: 180
      - field: git.recent_commits
        operator: equals
        value: 0
  actions:
    - type: notification
      params:
        title: "💡 커밋 알림"
        message: "3시간째 커밋이 없습니다..."
```

### 3. 스케줄 기반 작업

**규칙 예시**:
```yaml
# 매일 오후 9시 일일 리포트
- name: daily_recap_9pm
  trigger:
    type: time_based
    schedule:
      time: "21:00"
      days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
  actions:
    - type: tool_call
      params:
        tool_name: "daily_recap_notifier"
        tool_input: {}
```

## 실행 방법

### 방법 1: 직접 실행 (테스트)

```bash
# 환경변수 설정
export AGENT_MODE=daemon
export SCHEDULER_ENABLED=1
export SCHEDULER_POLL_SECONDS=300  # 5분마다

# 실행
python3 main.py
```

### 방법 2: Watchdog와 함께 (자동 재시작)

```bash
# Watchdog가 자동으로 재시작
python3 watchdog_runner.py
```

**장점**:
- 크래시 시 자동 재시작
- Exponential backoff
- Health check 지원
- 메트릭 로깅

### 방법 3: tmux/screen (SSH 세션 유지)

```bash
# tmux 세션 시작
tmux new -s boramclaw

# 데몬 실행
AGENT_MODE=daemon python3 watchdog_runner.py

# tmux 세션 분리: Ctrl+B, D
# 재연결: tmux attach -t boramclaw
```

### 방법 4: macOS 백그라운드 서비스 (자동 시작)

```bash
# LaunchAgent 파일 생성
cat > ~/Library/LaunchAgents/com.boram.boramclaw.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.boram.boramclaw</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/boram/BoramClaw/watchdog_runner.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/boram/BoramClaw</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>AGENT_MODE</key>
        <string>daemon</string>
        <key>SCHEDULER_ENABLED</key>
        <string>1</string>
        <key>ANTHROPIC_API_KEY</key>
        <string>your_api_key_here</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/boram/BoramClaw/logs/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/boram/BoramClaw/logs/daemon_error.log</string>
</dict>
</plist>
EOF

# 서비스 등록 및 시작
launchctl load ~/Library/LaunchAgents/com.boram.boramclaw.plist

# 상태 확인
launchctl list | grep boramclaw

# 중지
launchctl unload ~/Library/LaunchAgents/com.boram.boramclaw.plist
```

## 설정

### 1. Rules Engine 설정

**파일**: `config/rules.yaml`

```yaml
# 규칙 활성화 여부
enabled: true

# 규칙 체크 주기 (초)
check_interval: 300  # 5분마다

# 규칙 목록
rules:
  - name: my_rule
    enabled: true
    priority: high  # high, medium, low
    trigger:
      type: context_based  # 또는 time_based, inactivity, shell_pattern, context_change
      conditions: [...]
    actions: [...]
```

### 2. Scheduler 설정

**파일**: `.env`

```bash
# Scheduler 활성화
SCHEDULER_ENABLED=1

# 체크 주기 (초) - Rules Engine도 이 주기로 실행됨
SCHEDULER_POLL_SECONDS=300  # 5분

# Health Server (watchdog용)
HEALTH_SERVER_ENABLED=1
HEALTH_PORT=8080
```

### 3. 프라이버시 설정 (선택)

**파일**: `config/privacy.yaml` (아직 미구현, 예시)

```yaml
# 감시 제외 디렉토리
exclude_directories:
  - ~/.ssh
  - ~/.gnupg
  - ~/Private

# 감시 제외 앱
exclude_apps:
  - "1Password"
  - "Banking App"

# 감시 제외 URL 패턴
exclude_urls:
  - "*.bank.com"
  - "mail.google.com/mail/*"
```

## 모니터링

### 1. 로그 확인

**실시간 로그**:
```bash
tail -f logs/chat_log.jsonl | jq .
```

**Rules Engine 액션만 필터링**:
```bash
jq 'select(.event == "rules_engine_actions")' logs/chat_log.jsonl
```

**Heartbeat 확인**:
```bash
jq 'select(.event == "heartbeat")' logs/chat_log.jsonl | tail -5
```

### 2. Health Check

```bash
# HTTP health endpoint
curl http://127.0.0.1:8080/health

# 응답 예시
# {"status": "ok", "uptime_seconds": 12345}
```

### 3. macOS 알림 확인

규칙이 실행되면 macOS 알림 센터에 자동으로 알림이 표시됩니다.

**테스트**:
```bash
python3 -c "from utils.macos_notify import notify; notify('BoramClaw 테스트', '데몬이 정상 작동 중입니다!')"
```

## 규칙 타입

### 1. context_based (컨텍스트 기반)

현재 개발 활동 상태를 기반으로 트리거

**예시**: 3시간 코딩 후 커밋 없으면 알림

```yaml
trigger:
  type: context_based
  conditions:
    - field: session.duration_minutes
      operator: greater_than
      value: 180
    - field: git.recent_commits
      operator: equals
      value: 0
```

### 2. time_based (시간 기반)

특정 시간에 트리거

**예시**: 매일 오후 9시 일일 리포트

```yaml
trigger:
  type: time_based
  schedule:
    time: "21:00"
    days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
```

### 3. inactivity (비활동 감지)

일정 시간 비활동 시 트리거

**예시**: 30분 비활동 시 세션 종료 확인

```yaml
trigger:
  type: inactivity
  conditions:
    - field: context.last_activity_minutes_ago
      operator: greater_than
      value: 30
```

### 4. shell_pattern (Shell 패턴)

반복되는 명령어 패턴 감지

**예시**: 5회 이상 반복된 긴 명령어에 Alias 추천

```yaml
trigger:
  type: shell_pattern
  conditions:
    - field: shell.top_command_count
      operator: greater_than
      value: 5
    - field: shell.top_command_length
      operator: greater_than
      value: 30
```

### 5. context_change (컨텍스트 변경)

프로젝트 전환 등 감지

**예시**: Git 저장소 전환 시 이전 프로젝트 커밋 확인

```yaml
trigger:
  type: context_change
  conditions:
    - field: git.repo_changed
      operator: equals
      value: true
```

## 액션 타입

### 1. notification (macOS 알림)

```yaml
actions:
  - type: notification
    params:
      title: "제목"
      message: "내용"
      sound: "Glass"  # default, Glass, Ping, Hero, Sosumi 등
```

### 2. tool_call (BoramClaw 툴 실행)

```yaml
actions:
  - type: tool_call
    params:
      tool_name: "workday_recap"
      tool_input:
        mode: "daily"
```

### 3. log (로그 기록)

```yaml
actions:
  - type: log
    params:
      message: "규칙이 트리거되었습니다"
      level: "info"  # info, warning, error
```

### 4. shell (Shell 명령 실행)

**보안상 비활성화됨**

### 5. webhook (Webhook 호출)

**미구현 (향후 추가 예정)**

## 실전 예시

### 예시 1: 아침 출근 시 어제 요약

```yaml
- name: morning_recap
  enabled: true
  trigger:
    type: time_based
    schedule:
      time: "09:00"
      days: ["mon", "tue", "wed", "thu", "fri"]
  actions:
    - type: tool_call
      params:
        tool_name: "workday_recap"
        tool_input:
          mode: "daily"
    - type: notification
      params:
        title: "☀️ 굿모닝!"
        message: "어제 작업 요약이 준비되었습니다"
```

### 예시 2: 점심시간 휴식 권장

```yaml
- name: lunch_reminder
  enabled: true
  trigger:
    type: time_based
    schedule:
      time: "12:00"
      days: ["mon", "tue", "wed", "thu", "fri"]
      condition: session_active
  actions:
    - type: notification
      params:
        title: "🍽️ 점심시간"
        message: "건강한 식사를 하세요!"
```

### 예시 3: 야근 감지 및 수면 권장

```yaml
- name: late_night_warning
  enabled: true
  trigger:
    type: time_based
    schedule:
      time: "02:00"
      condition: session_active
  actions:
    - type: notification
      params:
        title: "🌙 수면 권장"
        message: "새벽 2시입니다. 내일을 위해 휴식하세요"
        sound: "Submarine"
```

### 예시 4: 반복 명령어 스크립트화 제안

```yaml
- name: frequent_command_alias
  enabled: true
  priority: low
  trigger:
    type: shell_pattern
    conditions:
      - field: shell.top_command_count
        operator: greater_than
        value: 5
      - field: shell.top_command_length
        operator: greater_than
        value: 30
  actions:
    - type: notification
      params:
        title: "⚡ Alias 추천"
        message: "자주 사용하는 긴 명령어가 있습니다. Alias를 만드시겠습니까?"
        sound: "Ping"
```

## 문제 해결

### 1. Rules Engine이 실행되지 않음

**확인사항**:
- `config/rules.yaml` 파일 존재 여부
- `enabled: true` 설정 확인
- 로그에서 `rules_engine_loaded` 이벤트 확인

```bash
jq 'select(.event == "rules_engine_loaded")' logs/chat_log.jsonl
```

### 2. 알림이 표시되지 않음

**확인사항**:
- macOS 알림 센터에서 "osascript" 또는 "Script Editor" 알림 허용 확인
- 테스트 알림 실행:
```bash
osascript -e 'display notification "테스트" with title "BoramClaw"'
```

### 3. 규칙이 트리거되지 않음

**디버깅**:
```bash
# 현재 컨텍스트 확인
python3 tools/get_current_context.py

# Rules Engine 단독 실행
python3 rules_engine.py
```

**조건 검증**:
- `field` 경로가 올바른지 확인 (예: `session.duration_minutes`)
- `operator` 연산자가 올바른지 확인
- `value` 값이 적절한지 확인

### 4. 메모리 사용량이 높음

**최적화**:
- `check_interval` 증가 (예: 600초 = 10분)
- 불필요한 규칙 비활성화 (`enabled: false`)
- 로그 rotation 확인

### 5. Watchdog가 계속 재시작함

**확인사항**:
- `logs/watchdog.log` 확인
- Health endpoint 응답 확인: `curl http://127.0.0.1:8080/health`
- `.env` 설정 확인 (특히 `ANTHROPIC_API_KEY`)

## 비용 최적화

### Daemon Mode 비용

**시나리오**: Rules Engine만 실행 (Claude API 호출 없음)
- **월간 비용**: **$0** (완전 로컬)

**시나리오**: 일일 리포트 자동 생성
- 매일 1회 `daily_recap_notifier` 실행
- 토큰 사용: ~1,500 토큰/회
- **월간 비용**: ~$0.74

**시나리오**: 주간 리포트 추가
- 주 1회 추가 (약 5,000 토큰)
- **월간 비용**: ~$0.95

**최적화 팁**:
1. 알림 액션만 사용 → 완전 무료
2. 툴 호출은 꼭 필요한 경우만
3. 로컬 데이터 캐싱 활용

## 다음 단계

### 1. 규칙 커스터마이징

`config/rules.yaml`을 수정하여 나만의 규칙 추가

### 2. 자연어로 질문

Claude Desktop에서 자연어로 질문:
- "오늘 뭐 했어?" → `workday_recap` 자동 호출
- "지금 무엇 작업 중이야?" → `get_current_context` 자동 호출

### 3. 웹 대시보드 (향후 추가 예정)

실시간 차트, 규칙 관리 UI 등

## VC Gateway 서비스 설치

스타트업 PC를 수집 게이트웨이로 운영하려면 `install_daemon.py`의 `--mode gateway`를 사용합니다.

```bash
# macOS / Linux 공통
python3 install_daemon.py --install --mode gateway --gateway-config config/vc_gateway.json
```

해제:

```bash
python3 install_daemon.py --uninstall
```

게이트웨이 설정 예시는 `config/vc_gateway.json.example`를 참고하세요.

---

**BoramClaw Daemon Mode**: 잠들지 않는 개발 비서 🤖

Made with ❤️ by Boram
