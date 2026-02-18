# BoramClaw MCP Server - Claude Desktop 연동 가이드

## 개요

BoramClaw의 MCP (Model Context Protocol) 서버를 통해 **Claude Desktop**에서 모든 BoramClaw 기능을 사용할 수 있습니다.

- 📝 **40+ 개의 커스텀 툴** 모두 접근 가능
- 🔄 **실시간 동기화**: 새 툴 추가 시 자동 반영
- 🖥️ **통합 UI**: Claude Desktop의 네이티브 인터페이스 활용
- 📊 **리포트 자동화**: `/today`, `/week` 등 직접 사용

## 전제 조건

1. **Claude Desktop** 설치 (https://claude.ai/download)
2. **BoramClaw** 설치 완료
3. **Python 3.10+** 환경

## 설정 방법

### 1. Claude Desktop 설정 파일 위치 확인

macOS:
```bash
~/.config/Claude/claude_desktop_config.json
```

Windows:
```
%APPDATA%\Claude\claude_desktop_config.json
```

Linux:
```bash
~/.config/Claude/claude_desktop_config.json
```

### 2. 설정 파일 편집

`~/.config/Claude/claude_desktop_config.json` 파일을 열고 다음 내용 추가:

```json
{
  "mcpServers": {
    "boramclaw": {
      "command": "python3",
      "args": ["/Users/boram/BoramClaw/mcp_server.py"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

**중요**: `/Users/boram/BoramClaw/mcp_server.py` 부분을 실제 BoramClaw 경로로 수정하세요.

경로 확인:
```bash
cd ~/BoramClaw
pwd  # 출력된 경로를 사용
```

### 3. 환경변수 설정 (선택)

`.env` 파일이 BoramClaw 디렉토리에 있어야 합니다. MCP 서버가 자동으로 로드합니다.

필수 환경변수:
```bash
ANTHROPIC_API_KEY=your_api_key_here
CUSTOM_TOOL_DIR=tools
TOOL_WORKDIR=.
```

### 4. Claude Desktop 재시작

1. Claude Desktop 완전 종료
2. 다시 실행
3. 대화 시작

## 사용 방법

### 툴 사용 예시

Claude Desktop 대화창에서:

```
오늘 개발 활동 리포트 보여줘
```

Claude가 자동으로 `workday_recap` 툴을 호출합니다:
```
{
  "mode": "daily"
}
```

### 직접 툴 지정

```
workday_recap 툴로 주간 리포트 생성해줘
```

또는:

```
daily_recap_notifier 실행해서 파일로 저장하고 알림 보내줘
```

### 사용 가능한 주요 툴

#### Phase 2: Developer's Digital Twin
- **workday_recap**: 통합 일일/주간 리포트
  - Screen, Git, Shell, Browser 데이터 통합
- **daily_recap_notifier**: 리포트 저장 + macOS 알림
- **screen_search**: screenpipe 화면 검색
- **git_daily_summary**: Git 커밋 분석
- **shell_pattern_analyzer**: Shell 명령어 패턴 분석
- **browser_research_digest**: 웹 브라우징 이력 분석

#### Built-in Tools
- **list_files**: 파일/디렉토리 목록
- **read_file**: 파일 읽기
- **write_file**: 파일 쓰기
- **run_shell**: Shell 명령 실행
- **schedule_daily_tool**: 스케줄 등록

#### 기타 커스텀 툴
- **arxiv_daily_digest**: arXiv 논문 검색
- **semantic_web_snapshot**: 웹 페이지 semantic 분석
- **telegram_send_message**: 텔레그램 메시지 전송
- **onchain_wallet_snapshot**: 온체인 지갑 스냅샷

## 동작 확인

### 1. MCP 서버 직접 테스트

터미널에서:
```bash
cd ~/BoramClaw
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"1.0"}}}' | python3 mcp_server.py 2>/dev/null | jq .
```

정상 응답:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "tools": {}
    },
    "serverInfo": {
      "name": "boramclaw",
      "version": "1.0.0"
    }
  }
}
```

### 2. 툴 목록 확인

```bash
cat << 'EOF' | python3 mcp_server.py 2>/dev/null | jq -r '.result.tools[] | .name' | head -10
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"1.0"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
EOF
```

출력 예시:
```
list_files
read_file
write_file
workday_recap
daily_recap_notifier
screen_search
git_daily_summary
...
```

### 3. Claude Desktop에서 확인

Claude Desktop 대화창에서:
```
사용 가능한 툴 목록 보여줘
```

또는:

```
workday_recap 툴이 있어?
```

## Troubleshooting

### MCP 서버가 시작되지 않는 경우

**증상**: Claude Desktop에서 툴을 찾을 수 없음

**해결**:
1. 경로 확인:
   ```bash
   ls -la ~/BoramClaw/mcp_server.py
   ```

2. Python 경로 확인:
   ```bash
   which python3
   ```
   - 출력된 경로를 `claude_desktop_config.json`에 사용

3. 권한 확인:
   ```bash
   chmod +x ~/BoramClaw/mcp_server.py
   ```

4. 수동 테스트:
   ```bash
   cd ~/BoramClaw
   python3 mcp_server.py
   ```
   입력:
   ```json
   {"jsonrpc":"2.0","id":1,"method":"ping"}
   ```
   Ctrl+D로 종료

### 환경변수 문제

**증상**: 툴 실행 시 "API key not found" 등의 에러

**해결**:
1. `.env` 파일 확인:
   ```bash
   cat ~/BoramClaw/.env | grep ANTHROPIC_API_KEY
   ```

2. MCP 설정에 env 추가:
   ```json
   {
     "mcpServers": {
       "boramclaw": {
         "command": "python3",
         "args": ["/Users/boram/BoramClaw/mcp_server.py"],
         "env": {
           "ANTHROPIC_API_KEY": "your_key_here",
           "CUSTOM_TOOL_DIR": "tools",
           "TOOL_WORKDIR": "/Users/boram/BoramClaw"
         }
       }
     }
   }
   ```

### 로그 확인

MCP 서버 로그 (stderr):
```bash
tail -f ~/Library/Logs/Claude/mcp*.log
```

또는 Claude Desktop 로그:
```bash
tail -f ~/Library/Logs/Claude/claude-desktop.log
```

### strict_workdir_only 에러

**증상**: "Blocked by strict_workdir_only" 에러

**해결**:
`.env`에 추가:
```bash
STRICT_WORKDIR_ONLY=0
```

또는 MCP 설정에서:
```json
{
  "env": {
    "STRICT_WORKDIR_ONLY": "0"
  }
}
```

## 고급 설정

### 여러 작업 디렉토리 지원

프로젝트별로 별도 MCP 서버 실행:

```json
{
  "mcpServers": {
    "boramclaw-project1": {
      "command": "python3",
      "args": ["/path/to/project1/BoramClaw/mcp_server.py"],
      "env": {
        "TOOL_WORKDIR": "/path/to/project1"
      }
    },
    "boramclaw-project2": {
      "command": "python3",
      "args": ["/path/to/project2/BoramClaw/mcp_server.py"],
      "env": {
        "TOOL_WORKDIR": "/path/to/project2"
      }
    }
  }
}
```

### 커스텀 툴 디렉토리

```json
{
  "env": {
    "CUSTOM_TOOL_DIR": "/path/to/custom/tools"
  }
}
```

### 타임아웃 설정

```json
{
  "env": {
    "TOOL_TIMEOUT_SECONDS": "600"
  }
}
```

## 보안 고려사항

1. **API Key 보호**: `.env` 파일을 `.gitignore`에 추가
2. **Workdir 제한**: `STRICT_WORKDIR_ONLY=1`로 파일 접근 제한
3. **권한 설정**: MCP에서는 모든 툴이 자동 허용되므로 민감한 툴 제거 권장

## 업데이트

### 새 툴 추가 시

1. `tools/` 디렉토리에 새 툴 파일 추가
2. Claude Desktop 재시작 (MCP 서버 자동 재로드)
3. 즉시 사용 가능

### BoramClaw 업데이트

```bash
cd ~/BoramClaw
git pull
```

Claude Desktop 재시작 필요

## 다음 단계

- **Phase 4**: Context Engine - 전체 맥락 통합
- **Phase 5**: Rules Engine - 규칙 기반 자동 액션

## 참고 자료

- [CLAUDE.md](CLAUDE.md) - 프로젝트 가이드
- [DAILY_RECAP_SETUP.md](DAILY_RECAP_SETUP.md) - 일일 리포트 설정
- [MCP 공식 문서](https://modelcontextprotocol.io/)
- [Claude Desktop](https://claude.ai/download)
