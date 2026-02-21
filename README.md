# BoramClaw 🤖

> **Developer's Digital Twin** - 개발자의 모든 활동을 추적하고 이해하는 AI 개인 비서

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Claude API](https://img.shields.io/badge/Claude-Sonnet%204.5-orange)](https://www.anthropic.com/claude)

## ✨ 핵심 가치

- 🔒 **100% 로컬** - 모든 데이터가 기기 내부에만 저장
- 🔐 **Privacy-First** - 외부 전송 없음
- 🤖 **자동화** - 규칙 기반 자동 액션
- 🧠 **지능형** - 컨텍스트 자동 파악
- 💰 **거의 무료** - 월 $0.70 (Claude Desktop 사용 시)
- 🗣️ **자연어** - "오늘 뭐 했어?" 같은 자연스러운 질문 지원

## 🎯 주요 기능

### 1. 실시간 컨텍스트 파악

```bash
User: 뭐하니 너 지금?
BoramClaw: 현재 Context Engine 구현 작업 중입니다.
           최근 30분간 python3 명령어를 25회 실행했고,
           git 명령어를 10회 실행했습니다.
```

**4개 데이터 소스 통합**:
- 📺 **Screen**: screenpipe OCR (선택)
- 📝 **Git**: 커밋 이력
- 💻 **Shell**: 명령어 패턴
- 🌐 **Browser**: 웹 검색 이력

### 2. 일일/주간 자동 리포트

```bash
User: 오늘 뭐 했지?
BoramClaw: 📊 오늘 개발 활동 리포트

           ✨ 오늘 활동: 명령어 296개, 웹 방문 19개

           💻 Shell: python3 25회, git 10회, npm 11회
           🌐 Browser: youtube.com 17회, google.com 2회
           📝 Git: 커밋 3개, 파일 5개 수정
```

**자동 스케줄**:
- 매일 21:00 자동 리포트 생성 + macOS 알림

### 3. 능동적 AI 비서 (Rules Engine)

**자동 알림 예시**:
- 💡 **커밋 리마인더**: 3시간 코딩 후 커밋 없으면 알림
- ☕ **휴식 권장**: 2시간 집중 작업 후 휴식 추천
- 🌙 **수면 권장**: 새벽 2시 작업 중이면 알림
- ⚡ **Alias 추천**: 반복되는 긴 명령어 감지
- 🔄 **프로젝트 전환**: 이전 프로젝트 커밋 확인

### 4. Claude Desktop 네이티브 통합

**MCP (Model Context Protocol) 지원**:
- Claude Desktop에서 자연어로 질문
- 50+ 커스텀 툴 자동 노출
- 실시간 데이터 조회

```
User: 지금 무엇 작업 중이야?
Claude: [get_current_context 툴 자동 호출]
        현재 Rules Engine 구현 중이고,
        최근 30분간 python3를 25회 실행했습니다.
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5: Proactive Intelligence (Rules Engine)             │
│  • 8 rule types, 6 trigger types, 5 action types            │
│  • 자동 커밋 알림, 휴식 권장, 일일 리포트                      │
└─────────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: Context Engine (실시간 맥락 통합)                  │
│  • 현재 작업 자동 파악, 세션 감지, 지능형 요약                  │
│  • "지금 뭐 하고 있어?" 자동 답변                             │
└─────────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Interface (MCP Server + Commands)                 │
│  • Claude Desktop 네이티브 통합                              │
│  • /today, /week, /context 명령어                           │
│  • 50+ 툴 노출                                               │
└─────────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Analyzer (리포트 생성 + 자동화)                    │
│  • 일일/주간 통합 리포트                                      │
│  • 자동 스케줄 (매일 21:00)                                  │
│  • macOS 알림 연동                                           │
└─────────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Observer (4개 데이터 소스)                         │
│  • Screen (screenpipe OCR)                                   │
│  • Git (커밋 이력)                                           │
│  • Shell (명령어 패턴)                                       │
│  • Browser (웹 검색)                                         │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 빠른 시작

### 1. 설치

```bash
# 저장소 클론
git clone https://github.com/yourusername/BoramClaw.git
cd BoramClaw

# 의존성 설치
pip install pyyaml

# (선택) screenpipe 설치
brew install screenpipe
```

### 2. 환경 설정

```bash
# .env 파일 생성
cat > .env << EOF
ANTHROPIC_API_KEY=your_api_key_here
CUSTOM_TOOL_DIR=tools
TOOL_WORKDIR=.
SCREENPIPE_API_URL=http://localhost:3030
EOF
```

### 3. 첫 실행

```bash
# Interactive 모드
python3 main.py

# 또는 Claude Desktop 연동 (MCP)
# ~/.config/Claude/claude_desktop_config.json 설정 필요
```

### 4. 자연어로 질문

```bash
User: 오늘 뭐 했어?
User: 지금 무엇 작업 중이야?
User: 이번 주 개발 진행상황 요약해줘
```

## 📖 문서

### 필수 문서

- **[CLAUDE.md](CLAUDE.md)** - 프로젝트 전체 가이드 (Claude Code용)
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - 프로젝트 요약 및 아키텍처
- **[NATURAL_LANGUAGE_DEMO.md](NATURAL_LANGUAGE_DEMO.md)** - 자연어 인터페이스 사용법
- **[DAEMON_MODE.md](DAEMON_MODE.md)** - 24/7 자동 실행 가이드

### 설정 가이드

- **[MCP_SETUP_GUIDE.md](MCP_SETUP_GUIDE.md)** - Claude Desktop 연동 방법
- **[DAILY_RECAP_SETUP.md](DAILY_RECAP_SETUP.md)** - 일일 리포트 자동화
- **[COST_ANALYSIS.md](COST_ANALYSIS.md)** - 비용 분석 및 ROI

## 💡 사용 예시

### 시나리오 1: 아침 출근

```bash
User: 어제 뭐까지 했더라?

BoramClaw: 어제는 MCP Server 구현까지 완료했습니다.
           커밋 3개, 파일 5개 수정.
           주요 작업: gateway.py 리팩토링,
                     mcp_server.py 생성
```

### 시나리오 2: 주간 회의 준비

```bash
User: 이번 주 개발 진행상황 요약해줘

BoramClaw: 이번 주 커밋 15개, 주요 작업:
           - Phase 1-5 완료 (Observer ~ Proactive Intelligence)
           - MCP Server 구현
           - Rules Engine 완료

           블로커: 없음
           다음 주 계획: 웹 대시보드 (선택)
```

### 시나리오 3: 집중 시간 확인

```bash
User: 오늘 몇 시간 코딩했어?

BoramClaw: 총 5시간 30분, 2개 세션:
           - 오전 10:00-13:00 (3시간)
           - 오후 14:30-17:00 (2.5시간)

           주요 활동: Python 개발 (85%)
```

### 시나리오 4: 자동 알림 (Daemon Mode)

```
🔔 [오후 9:00]
💡 BoramClaw: 오늘 일일 리포트가 준비되었습니다!
              커밋 3개, 명령어 296개, 웹 방문 19개

🔔 [새벽 2:00]
🌙 BoramClaw: 새벽 2시입니다. 내일을 위해 휴식하세요.
```

## 💰 비용

### 월간 비용 (시나리오별)

| 사용 방식 | 월 비용 | 설명 |
|-----------|---------|------|
| **CLI 전용** | **$0** | 100% 로컬 실행 |
| **Claude Desktop 경량** | **$0.30** | 주 2-3회 리포트 조회 |
| **Claude Desktop 중간** | **$0.70** | 일일 리포트 + 주간 리포트 |
| **Claude Desktop 헤비** | **$2.20** | 대화형 사용 |

**평균: $0.70/월** (스타벅스 커피 1/7잔 가격)

### ROI (투자 대비 효과)

- **시간 절약**: 30분/일 → 월 15시간
- **시급 $50 기준**: $750/월 가치
- **ROI**: **1,070배**

자세한 분석: [COST_ANALYSIS.md](COST_ANALYSIS.md)

## 🛠️ 기술 스택

### Backend
- **Python 3.10+** - 메인 언어
- **YAML** - 규칙 정의
- **JSON** - 데이터 포맷
- **SQLite** - 브라우저 이력 (Chrome/Safari)

### Integrations
- **screenpipe** - 화면 OCR (Rust) (선택)
- **MCP (Model Context Protocol)** - Claude Desktop 통합
- **macOS osascript** - 네이티브 알림

### APIs
- **Claude API** (선택) - Claude Desktop 사용 시
- **screenpipe REST API** - 로컬 서버 (3030 포트)

## 📦 프로젝트 구조

```
BoramClaw/
├── main.py                      # 메인 진입점
├── mcp_server.py               # MCP 서버
├── context_engine.py           # Context Engine
├── rules_engine.py             # Rules Engine
├── gateway.py                  # Claude API wrapper
├── config/
│   ├── rules.yaml              # 규칙 정의
│   └── rules.yaml.example      # 규칙 템플릿
├── tools/                      # 50+ 커스텀 툴
│   ├── screen_search.py
│   ├── git_daily_summary.py
│   ├── shell_pattern_analyzer.py
│   ├── browser_research_digest.py
│   ├── workday_recap.py
│   ├── daily_recap_notifier.py
│   └── get_current_context.py
├── utils/
│   └── macos_notify.py         # macOS 알림
├── logs/
│   └── summaries/daily/        # 일일 리포트
└── docs/
    ├── CLAUDE.md
    ├── PROJECT_SUMMARY.md
    ├── NATURAL_LANGUAGE_DEMO.md
    ├── DAEMON_MODE.md
    ├── MCP_SETUP_GUIDE.md
    └── COST_ANALYSIS.md
```

## 🧪 테스트

### 종합 테스트

```bash
# Phase별 테스트
pytest tests/

# 또는 수동 테스트
python3 tools/get_current_context.py
python3 tools/workday_recap.py --tool-input-json '{"mode":"daily"}'
python3 rules_engine.py
```

**결과**:
```
Phase 1: Observer Layer        ✅ 4/4 통과
Phase 2: Analyzer Layer        ✅ 2/2 통과
Phase 3: MCP Server            ✅ 정상
Phase 4: Context Engine        ✅ 정상
Phase 5: Rules Engine          ✅ 8개 규칙 로드

총 테스트: 100% 통과
```

## 🌟 주요 차별점

### vs OpenClaw
- **OpenClaw**: 메시징 허브 (13+ 채널 통합)
- **BoramClaw**: 개발자 컨텍스트 엔진 (4개 소스 통합)

### vs ActivityWatch
- **ActivityWatch**: 단순 활동 추적
- **BoramClaw**: 지능형 컨텍스트 파악 + 자동 액션

### vs GitHub Copilot
- **Copilot**: 코드 자동완성 ($10/월)
- **BoramClaw**: 전체 작업 맥락 파악 ($0.70/월)

## 📈 향후 계획 (선택)

- **Phase 6**: 로컬 LLM 통합 (Ollama)
- **Phase 7**: 웹 대시보드 (실시간 차트)
- **Phase 8**: 팀 협업 (멀티 유저)
- **Phase 9**: IDE 플러그인 (VSCode, JetBrains)
- **Phase 10**: 모바일 앱 (iOS/Android)

## 🧩 OpenClaw VC Mode (P1)

공용 폴더 + 동의 기반으로 스타트업 데이터를 수집하는 VC/액셀러레이터 워크플로우입니다.

### 누구를 위한 가이드인가

- VC/AC 운영자: 스타트업 자료를 정기 수집하고 승인 후 보고/발송하려는 팀
- 스타트업 담당자: 지정된 폴더만 안전하게 공유하고 증빙 제출 자동화를 원하는 팀
- 비개발자 사용자: 설치/실행을 명령어 복붙 중심으로 진행하려는 사용자

### 시스템 구성 (2대 PC)

- 중앙 오케스트레이터 PC(VC 측): 텔레그램 명령 수신, 수집 요청, 암호화 저장, 승인 큐 관리
- 로컬 게이트웨이 PC(스타트업 측): 동의된 폴더를 읽기 전용으로 노출하는 API 서버

핵심 원칙:

- 기본은 `공유 폴더` 모델
- 외부 전송(메일)은 승인 후 실행
- full-access는 가능하지만 과수집 위험이 높아 파일럿에서만 제한적으로 권장

---

## 0) 완전 초기 설치 (아무것도 없는 PC 기준)

### 공통 준비물

- 인터넷 연결
- Python 3.10 이상
- Git

### macOS

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git python@3.11
```

### Windows (PowerShell 관리자 권한)

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.11 -e
```

`winget`이 없다면 Python/Git 공식 설치 프로그램으로 수동 설치 후 진행합니다.

### Linux (Ubuntu 예시)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

---

## 1) VC(수집자) 설치 루프

### 1-1. 저장소 설치

```bash
git clone https://github.com/yourusername/BoramClaw.git
cd BoramClaw

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
python3 -m pip install pyyaml
```

Windows CMD/PowerShell에서는 `source` 대신 아래를 사용합니다.

```powershell
.venv\Scripts\activate
```

### 1-2. VC 설정 파일 자동 생성

```bash
python3 main.py --setup-vc central
```

비대화형 예시:

```bash
python3 main.py --setup-vc central --setup-vc-non-interactive
```

생성되는 핵심 파일:

- `config/vc_tenants.json`
- `.env`

---

## 2) 스타트업(게이트웨이) 설치 루프

### 2-1. 저장소 설치

VC와 동일하게 설치합니다.

```bash
git clone https://github.com/yourusername/BoramClaw.git
cd BoramClaw

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

### 2-2. 게이트웨이 설정 파일 자동 생성

```bash
python3 main.py --setup-vc gateway
```

비대화형 예시:

```bash
python3 main.py --setup-vc gateway --setup-vc-non-interactive
```

생성되는 핵심 파일:

- `config/vc_gateway.json`
- `scripts/windows/start_gateway.bat`
- `scripts/windows/install_gateway_service.bat`
- `scripts/windows/uninstall_gateway_service.bat`

### 2-3. 게이트웨이 실행

macOS/Linux:

```bash
python3 vc_gateway_agent.py --config config/vc_gateway.json --host 0.0.0.0 --port 8742
```

Windows:

```text
scripts\windows\start_gateway.bat
```

백그라운드 등록(Windows):

```text
scripts\windows\install_gateway_service.bat
```

---

## 3) 동의(Consent) 운영 방식

서면 동의(종이/스캔) 운영 가능합니다. P1에서는 실무적으로 아래 절차를 권장합니다.

### 3-1. 동의서 필수 항목

- 수집 목적
- 수집 범위(폴더/문서유형)
- 보관 기간
- 제3자 제공/발송 범위
- 철회 방법

### 3-2. 운영 등록 방식

1. 동의서 ID 발급  
예: `CONSENT-ACME-2026-02-19-v1`

2. 동의서 원본/스캔 보관  
파일 해시(SHA256)와 함께 문서대장 기록 권장

3. 시스템 반영  
`/vc scope` 명령으로 동의 ID와 보관기간 등록

```text
/vc scope acme allow=desktop_common/Finance,desktop_common/IR deny=*private*,*.key,*.pem docs=business_registration,tax_invoice,social_insurance consent=CONSENT-ACME-2026-02-19-v1 retention=365
```

주의:

- 현재 P1은 `consent_reference` 저장/조회는 가능하지만, 미입력 강제 차단은 운영 절차로 보완해야 합니다.
- 운영에서는 collect 전에 항상 `/vc scope <startup_id>` 확인을 표준 절차로 두는 것을 권장합니다.

---

## 4) 첫 수집 실행 (실사용 루프)

### 4-1. VC 측 실행

```bash
python3 main.py --telegram
```

### 4-2. 텔레그램/CLI에서 순서대로 실행

```text
/vc register acme Acme AI
/vc bind-folder acme http://<startup-gateway-ip>:8742 desktop_common
/vc onboard acme 7d
/vc scope acme
/vc collect acme 7d
/vc pending acme
/vc approve <approval_id> by=<operator>
/vc report acme weekly
```

### 4-3. 자주 쓰는 명령

```text
/vc help
/vc verify acme
/vc dashboard acme 30d
/vc scope-audit acme 100 reject
/vc reject <approval_id> <reason>
```

---

## 5) 저장 구조

- 암호화 번들: `vault/<startup_id>/<yyyy>/<mm>/<dd>/<collection_id>.bin`
- 메타데이터: `vault/<startup_id>/<yyyy>/<mm>/<dd>/<collection_id>.json`
- 키 저장소: `data/vc_keys.json` (AES-256-GCM)
- 운영 DB: `data/vc_platform.db`

---

## 6) full-access 모델 사용 시 주의

full-access는 기술적으로 가능하지만 과수집 위험이 큽니다.

권장 운영:

- 파일럿 단계에서만 제한 사용
- `deny` 패턴을 강하게 적용
- `allowed_doc_types`를 비워두지 않기
- 승인 게이트를 반드시 유지

권장 deny 예시:

```text
*private*,*diary*,*.env,*.key,*.pem,*/AppData/*,*/.ssh/*
```

---

## 7) 비개발자 트러블슈팅

### Python 실행 오류

Windows에서 Python 경로 인식이 안 되면 환경변수 지정:

```text
BORAMCLAW_PYTHON_BIN=C:\Python311\python.exe
```

관련 변수:

```text
BORAMCLAW_MIN_PYTHON=3.10
BORAMCLAW_WINDOWS_TASK_SCHEDULE=ONLOGON|DAILY
BORAMCLAW_WINDOWS_TASK_DELAY=0000:30
BORAMCLAW_WINDOWS_TASK_USER=<windows_user>
```

### 게이트웨이 연결 실패

- 스타트업 PC에서 `vc_gateway_agent.py`가 실행 중인지 확인
- VC PC에서 해당 IP:PORT(예: `8742`) 접근 가능한지 확인
- 사내 방화벽/백신에서 포트 차단 여부 확인

### 텔레그램 명령이 동작하지 않을 때

- `.env`의 `TELEGRAM_BOT_TOKEN` 확인
- `.env`의 `TELEGRAM_ALLOWED_CHAT_ID` 확인
- `python3 main.py --telegram`로 브릿지 실행 여부 확인

---

## 8) 운영 체크리스트

- 스타트업별 동의서 ID 발급 및 원본 보관
- `/vc scope`에 allow/deny/docs/consent/retention 반영
- `/vc onboard` 성공 후 본수집 진행
- `pending -> approve/reject` 승인 로그 관리
- 월 1회 scope-audit 및 리스크 대시보드 점검

## 🤝 기여

기여는 언제나 환영합니다!

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 라이선스

MIT License - 자유롭게 사용, 수정, 배포 가능

## 🙏 감사의 말

이 프로젝트는 다음 오픈소스 프로젝트에서 영감을 받았습니다:

- **[OpenClaw](https://github.com/OpenClaw/openclaw)** - 메시징 통합 아이디어
- **[screenpipe](https://github.com/mediar-ai/screenpipe)** - 화면 캡처 기술
- **[Claude Code](https://claude.ai/code)** - MCP 프로토콜

## 📞 지원

- 📝 **Issues**: [GitHub Issues](https://github.com/yourusername/BoramClaw/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/yourusername/BoramClaw/discussions)
- 📧 **Email**: your.email@example.com

---

**BoramClaw: Developer's Digital Twin**

"당신의 모든 개발 활동을 이해하는 AI 비서"

Made with ❤️ by Boram
