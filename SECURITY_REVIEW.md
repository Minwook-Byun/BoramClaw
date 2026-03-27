# BoramClaw 보안 검토 (2026-02-18)

## 🔒 보안 평가 요약

**전반적 평가**: ✅ **안전함** (OpenClaw 대비 공격 표면 최소화)
**위험도**: 🟢 낮음 (로컬 중심, 외부 연동 제한적)

---

## 1️⃣ 데이터 프라이버시

### ✅ 강점: 100% 로컬 처리
```
브라우저 히스토리 → SQLite 직접 읽기 → 로컬 분석
셸 히스토리 → ~/.zsh_history 파싱 → 로컬 분석
Git 커밋 → git log 실행 → 로컬 분석
```

- **외부 전송 없음**: 개발 활동 데이터는 절대 외부로 나가지 않음
- **Claude API 전송 내용**: 사용자 명령어와 요약된 결과만 (원본 데이터 안 감)
- **Telegram 전송 내용**: 생성된 리포트만 (코드/파일 내용 제외)

### ⚠️ 주의점
1. **텔레그램 메시지는 암호화 전송**되지만, 텔레그램 서버에 저장됨
   - 민감한 코드/파일 경로가 리포트에 포함될 수 있음
   - **개선 방안**: 리포트에 파일 전체 경로 대신 상대 경로 사용

2. **로그 파일에 모든 활동 기록**
   - `logs/chat_log.jsonl`: 대화 내용 포함
   - `logs/telegram_bot.log`: 텔레그램 메시지 포함
   - **현재 상태**: API 키는 마스킹됨 (`logger.py:58`)
   - **권장**: 로그 파일 권한 `chmod 600`

---

## 2️⃣ API 키 관리

### ✅ 현재 구현
```python
# config.py
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # .env에서 로드
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
```

**장점**:
- `.env` 파일은 `.gitignore`에 포함 (Git 추적 안 됨)
- 환경 변수로 분리 (코드에 하드코딩 안 됨)

**단점**:
- `.env` 파일은 **평문**으로 저장됨
- 파일 시스템 권한만으로 보호

### 🔐 개선 방안
```python
# config.py의 keychain 지원
KEYCHAIN_SERVICE_NAME=BoramClaw
KEYCHAIN_ACCOUNT_NAME=anthropic_api_key
```

**이미 구현됨!** (config.py:102-120)
- macOS Keychain 우선 사용
- `.env` fallback

**사용법**:
```bash
# Keychain에 API 키 저장 (한 번만)
security add-generic-password -s BoramClaw -a anthropic_api_key -w "sk-ant-..."
security add-generic-password -s BoramClaw -a telegram_bot_token -w "123456:ABC..."
```

**권장**: `.env` 대신 Keychain 사용

---

## 3️⃣ 명령 실행 보안

### ✅ 위험 명령어 차단
```python
# main.py:436 - 금지 명령어 목록
BLOCKED_COMMANDS = [
    "rm -rf", "sudo", "shutdown", "reboot",
    "mkfs", "dd", "fdisk", "kill -9",
    "chmod 777", "chown", "> /dev/"
]
```

### ✅ Workdir 제한
```python
# .env
STRICT_WORKDIR_ONLY=1
TOOL_WORKDIR=.
```

**효과**:
- 파일 읽기/쓰기는 `TOOL_WORKDIR` 내부만 가능
- `../` 상위 디렉토리 접근 차단
- 절대 경로 (`/etc/passwd`) 차단

**Audit Hook** (main.py):
```python
sys.addaudithook(audit_hook)  # 파일 접근 모니터링
```

### ⚠️ 주의점
1. **`run_shell`은 여전히 강력함**
   - 금지 명령어를 우회할 수 있는 방법 존재 (예: `r\m -rf`)
   - **개선 방안**: 셸 실행을 `subprocess` 화이트리스트로 전환

2. **`run_python`은 strict 모드에서 비활성화**
   - 보안상 올바른 선택

---

## 4️⃣ 네트워크 보안

### 외부 API 호출 목록
1. **Claude API** (`api.anthropic.com`)
   - TLS 암호화 ✅
   - API 키 인증 ✅

2. **Telegram Bot API** (`api.telegram.org`)
   - TLS 암호화 ✅
   - Bot Token 인증 ✅
   - **Chat ID 검증**: 허용된 Chat ID만 응답
   ```python
   if chat_id != allowed_chat_id:
       print(f"⚠️  무시: 허용되지 않은 Chat ID {chat_id}")
       continue
   ```

3. **선택적 통합** (사용자가 설정한 경우만)
   - Gmail API
   - Google Calendar API
   - GitHub API
   - arXiv API (공개)

**차단 메커니즘**:
- 사용하지 않는 API는 도구를 로드하지 않음
- 권한 게이트 (`TOOL_PERMISSIONS_JSON`)

---

## 5️⃣ 텔레그램 봇 보안

### ✅ 구현된 보안 기능
1. **Chat ID 화이트리스트**
   ```python
   TELEGRAM_ALLOWED_CHAT_ID=8565866309  # 본인만
   ```

2. **Bot Token 보호**
   - `.env`에 저장, Git 추적 안 됨

3. **Long Polling** (Webhook 아님)
   - 로컬에서 텔레그램 서버로 연결 (방화벽 설정 불필요)
   - 서버가 로컬 머신에 접근할 수 없음

### ⚠️ 위험 시나리오
**시나리오 1**: Bot Token 유출 시
- 공격자가 Bot Token을 탈취하면?
- **영향**: Chat ID 화이트리스트로 인해 **공격자가 명령 실행 불가**
- **예외**: Chat ID까지 유출되면 **명령 실행 가능** ❌

**시나리오 2**: 중간자 공격 (MITM)
- 텔레그램 API는 HTTPS 사용 → 기본적으로 안전
- 단, 신뢰할 수 없는 네트워크에서는 위험

**개선 방안**:
1. **2FA 추가**: 민감한 명령 실행 시 추가 인증
2. **Rate Limiting**: 같은 명령 연속 실행 제한
3. **명령 로그 + 알림**: 예상치 못한 명령 실행 시 알림

---

## 6️⃣ OpenClaw와 비교

| 항목 | OpenClaw | BoramClaw |
|------|----------|-----------|
| **외부 플랫폼 연동** | 13개 (Slack, Discord, ...) | 1개 (Telegram) |
| **공격 표면** | 넓음 (여러 OAuth, Webhook) | 좁음 (단일 Bot API) |
| **데이터 전송** | 메시지 전체 통합/전송 | 로컬 분석, 요약만 전송 |
| **서버 필요** | 필요 (Webhook) | 불필요 (Long Polling) |
| **민감 정보 노출** | 높음 (채팅 내용 통합) | 낮음 (개발 활동 메타데이터만) |

**결론**: BoramClaw가 OpenClaw보다 **보안 리스크 낮음**

---

## 7️⃣ 권장 보안 강화 조치

### 즉시 적용 가능
1. ✅ **Keychain 사용** (API 키 평문 제거)
   ```bash
   security add-generic-password -s BoramClaw -a anthropic_api_key -w "your_key"
   security add-generic-password -s BoramClaw -a telegram_bot_token -w "your_token"
   ```

2. ✅ **로그 파일 권한**
   ```bash
   chmod 600 logs/*.log
   chmod 600 logs/*.jsonl
   ```

3. ✅ **.env 권한**
   ```bash
   chmod 600 .env
   ```

4. ✅ **민감 경로 필터링**
   - 리포트에 홈 디렉토리 전체 경로 대신 `~/` 사용
   - 예: `/Users/boram/BoramClaw/main.py` → `~/BoramClaw/main.py`

### 중장기 개선
1. **명령 실행 화이트리스트**
   ```python
   ALLOWED_COMMANDS = ["git", "ls", "cat", "grep", "pytest"]
   # run_shell에서 명령어 첫 단어가 화이트리스트에 있는지 확인
   ```

2. **Rate Limiting**
   ```python
   # 같은 명령 5초 내 재실행 차단
   last_commands = {}
   if (time.time() - last_commands.get(command, 0)) < 5:
       return "Too fast, wait 5 seconds"
   ```

3. **End-to-End 암호화**
   - Telegram MTProto는 서버-클라이언트 암호화만 제공
   - 진정한 E2E는 Secret Chat만 가능 (Bot API 미지원)
   - **대안**: 민감 데이터는 로컬 암호화 후 전송

4. **2FA for 위험 명령**
   ```python
   # 예: "이번 주 코드 전체" 같은 민감 리포트 요청 시
   if is_sensitive_command(command):
       send_message(chat_id, "인증 코드를 입력하세요:")
       # 사용자 응답 대기 및 검증
   ```

---

## 8️⃣ 보안 체크리스트

### ✅ 현재 상태
- [x] API 키를 Git에 커밋하지 않음
- [x] `.env` 파일이 `.gitignore`에 포함됨
- [x] 위험 셸 명령어 차단
- [x] Workdir 제한 (`STRICT_WORKDIR_ONLY=1`)
- [x] 텔레그램 Chat ID 화이트리스트
- [x] TLS 암호화 통신 (Claude, Telegram)
- [x] 로그에서 API 키 마스킹
- [x] Keychain 지원 구현 (선택 사항)

### ⚠️ 권장 개선
- [ ] `.env` 파일 권한 `chmod 600`
- [ ] `logs/` 디렉토리 권한 `chmod 700`
- [ ] Keychain으로 API 키 이전 (.env 삭제)
- [ ] 리포트에서 전체 경로 → 상대 경로 변환
- [ ] Rate Limiting 구현
- [ ] 민감 명령 2FA 추가

### 🔮 장기 고려사항
- [ ] 명령 실행 화이트리스트 전환
- [ ] 로그 자동 암호화 (at rest)
- [ ] 보안 감사 로그 (별도 파일, 변조 방지)
- [ ] Webhook 대신 Long Polling 유지 (현재 구현)

---

## 9️⃣ 최종 평가

### 🟢 **안전함** (단, 권장 조치 필요)

**주요 장점**:
1. **로컬 중심**: 민감 데이터를 외부로 전송하지 않음
2. **최소 권한**: 필요한 API만 연동
3. **제한된 공격 표면**: 텔레그램 단일 채널
4. **Chat ID 검증**: 무단 접근 차단

**주요 위험**:
1. **API 키 평문 저장** (.env)
   - **해결**: Keychain 사용
2. **로그 파일 민감 정보** (파일 경로, 명령어)
   - **해결**: 로그 권한 강화, 상대 경로 사용
3. **텔레그램 서버 의존**
   - **완화**: 민감 정보는 텔레그램으로 전송 안 함

**비교**: OpenClaw 대비 **훨씬 안전**
- 공격 표면: OpenClaw(13개 플랫폼) vs BoramClaw(1개)
- 데이터 노출: OpenClaw(전체 채팅) vs BoramClaw(메타데이터만)

---

## 📋 즉시 실행할 명령어

```bash
# 1. 파일 권한 강화
chmod 600 .env
chmod 600 logs/*.log 2>/dev/null || true
chmod 600 logs/*.jsonl 2>/dev/null || true
chmod 700 logs/

# 2. Keychain에 API 키 저장 (권장)
# 텔레그램 토큰
security add-generic-password -s BoramClaw -a telegram_bot_token \
  -w "$(grep TELEGRAM_BOT_TOKEN .env | cut -d= -f2)"

# Anthropic API 키
security add-generic-password -s BoramClaw -a anthropic_api_key \
  -w "$(grep ANTHROPIC_API_KEY .env | cut -d= -f2)"

# 3. .env에서 민감 정보 제거 (Keychain 사용 시)
# .env 파일을 백업하고 API 키 라인을 주석 처리
cp .env .env.backup
sed -i '' 's/^ANTHROPIC_API_KEY=/#ANTHROPIC_API_KEY=/' .env
sed -i '' 's/^TELEGRAM_BOT_TOKEN=/#TELEGRAM_BOT_TOKEN=/' .env

# 4. 검증
ls -la .env logs/
echo "✅ 권한 설정 완료"
```

---

**작성자**: Claude Sonnet 4.5
**작성일**: 2026-02-18
**검토 주기**: 분기별 (3개월)
