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

### 5. Codex-backed Advanced Workflows

- `/advanced` - advanced 워크플로우 상태 확인
- `/review engineering|pm|cpo` - Codex CLI 기반 역할별 리뷰
- `/wrapup` - 프롬프트/로컬 Git/workdir evidence를 포함한 세션 랩업 및 다음 액션 정리
- `/delegate` - 기존 멀티에이전트 라우팅과 함께 사용
- `LLM_PROVIDER=codex` 시 선택된 BoramClaw tool schema를 manifest로 Codex에 전달
- `/wrapup` 결과와 Codex rollout 분석값은 `logs/session_timeseries.jsonl`에 누적 가능
- `python3 tools/daily_retrospective_post.py --tool-context-json '{"workdir":"."}' --tool-input-json '{"target_date":"2026-03-12"}'` 로 특정 날짜의 상세 회고 Markdown + AutoDashboard 포스트를 생성 가능
- `python3 session_timeseries.py --backfill-codex --start-date 2026-03-09 --end-date 2026-03-12 --workdir .` 로 Codex 세션 백필 가능
- `python3 session_timeseries.py --render-svg --workdir . --input-file logs/session_timeseries.jsonl --svg-output logs/reviews/session_timeseries.svg --kinds codex_rollout` 로 정적 SVG 시각화 생성 가능
- `python3 tools/autodashboard_timeseries_sync.py --tool-context-json '{"workdir":"."}'` 로 AutoDashboard `snapshots.jsonl` 또는 append API에 동기화 가능
- `python3 tools/daily_wrapup_pipeline.py --tool-context-json '{"workdir":"."}'` 로 당일 Codex rollout 백필 + evidence-first wrapup + 상세 회고 포스트 + AutoDashboard 동기화를 한 번에 실행 가능
- `python3 install_autodashboard_sync.py --install --start-at 2026-03-13T18:30:00+09:00` 로 macOS `launchd`에 매일 18:30 KST 자동 wrapup + 회고 포스팅 + 누적 동기화 등록 가능

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
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=your_api_key_here
CODEX_COMMAND=codex
CUSTOM_TOOL_DIR=tools
TOOL_WORKDIR=.
SCREENPIPE_API_URL=http://localhost:3030
ADVANCED_FEATURES_ENABLED=1
ADVANCED_PROVIDER=codex
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
