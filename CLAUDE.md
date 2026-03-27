# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BoramClaw is an autonomous AI agent system that extends Claude's capabilities through dynamic tool loading and execution. The agent can create, modify, and execute Python tools at runtime to solve tasks. All interactions are in Korean.

## Core Architecture

### Main Components

- **[main.py](main.py)** - Central orchestrator implementing the tool-calling loop
  - Entry point for interactive (`AGENT_MODE=interactive`) and daemon (`AGENT_MODE=daemon`) modes
  - Manages conversation history and tool execution rounds
  - Contains built-in tools (filesystem, shell, Python execution)

- **[gateway.py](gateway.py)** - Claude API wrapper with request serialization
  - `ClaudeChat`: API client with conversation history management
  - `RequestQueue`: Lane-based serialization for safe concurrent access
  - Supports forced tool use via `tool_choice` parameter

- **[config.py](config.py)** - Configuration loading and validation
  - `BoramClawConfig`: Dataclass holding all runtime settings
  - Loads from `.env` with sensible defaults
  - Environment variable helpers for bool/int parsing

- **[tool_executor.py](tool_executor.py)** - Tool execution with permission control
  - Wraps tool calls with approval gates (allow/prompt/deny)
  - Dry-run mode support
  - Audit logging for all tool executions

- **[scheduler.py](scheduler.py)** - Job scheduling with heartbeat monitoring
  - `JobScheduler`: Background thread for periodic job execution
  - Checks `tasks/pending.txt` for pending work
  - Configurable poll interval via `SCHEDULER_POLL_SECONDS`

- **[watchdog_runner.py](watchdog_runner.py)** - Process monitoring and auto-restart
  - Monitors main.py process health
  - Exponential backoff for crash recovery
  - Health check via HTTP endpoint (`/health`)
  - Metrics logging to `logs/recovery_metrics.jsonl`

- **[logger.py](logger.py)** - Structured logging with rotation
  - JSONL format for machine-readable logs
  - Rotating file handler (10MB per file, 5 backups)
  - Sensitive data masking (API keys, tokens)

### Tools System

Custom tools live in `tools/*.py`. Each tool must implement:

```python
TOOL_SPEC = {
    "name": "tool_name",
    "description": "What the tool does",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}

def run(input_data: dict, context: dict) -> Any:
    # Tool implementation
    return result
```

**CLI contract**: Tools must support these flags:
- `--tool-spec-json`: Print TOOL_SPEC as JSON
- `--tool-input-json <json>`: Tool input arguments
- `--tool-context-json <json>`: Execution context (workdir, timeout, etc.)

**Tool discovery**: Tools are loaded dynamically by scanning `tools/*.py` at runtime. Changes to tool files trigger chat session recreation with history summarization.

**Execution model**: Tools run as independent subprocesses with audit hooks to enforce workdir boundaries (`STRICT_WORKDIR_ONLY=1`).

## Development Commands

### Running the Agent

**Interactive mode** (default):
```bash
python3 main.py
```

**Daemon mode** (for 24/7 operation):
```bash
AGENT_MODE=daemon python3 main.py
```

**With watchdog** (auto-restart on crash):
```bash
python3 watchdog_runner.py
```

### Testing

Run all tests:
```bash
pytest tests/
```

Run specific test file:
```bash
pytest tests/test_agent_core.py -v
```

Run with TDD cycle tracking:
```bash
python3 tdd_cycles.py
```

### Tool Management

**List available tools**:
```
/tools
```

**Reload tools after changes**:
```
/reload-tools
```

**Execute tool directly**:
```
/tool <tool_name> {"arg": "value"}
```

**Create new tool**: Use the `create_or_update_custom_tool_file` built-in tool or directly write to `tools/<name>.py`.

### Scheduling

**Schedule daily job**:
```
/tool schedule_daily_tool {"tool_name":"my_tool","time":"09:00","tool_input":{}}
```

**List schedules**:
```
/schedules
```

Schedule definitions are stored in `schedules/jobs.json`.

## Key Architectural Patterns

### ReAct Loop

The agent follows a Thought → Action → Observation pattern:

1. User provides input
2. Claude decides which tool(s) to call (Action)
3. Tools execute locally and return results (Observation)
4. Results feed back into Claude for next decision (Thought)
5. Loop continues until Claude produces final text response

Implementation: [main.py:573-620](main.py#L573-L620)

### Tool-First Principle

The system prompt instructs the agent to:
1. Search for an appropriate tool first
2. If no tool exists, create one by reading examples from `tools/`
3. Save the new tool to `tools/` using `save_text_file`
4. Use the tool to solve the task

This enables the agent to expand its own capabilities.

### Filesystem-First Tool Registry

Tools are discovered by scanning `tools/*.py` on each invocation. No persistent registry cache exists. Benefits:
- Always reflects current filesystem state
- Simple mental model
- No cache invalidation issues

On tool file changes, the chat session resets with a brief summary to maintain context consistency.

### Security Model

**Workdir isolation**: When `STRICT_WORKDIR_ONLY=1` (default):
- File operations restricted to `TOOL_WORKDIR` and subdirectories
- Shell commands with `..` or absolute paths are blocked
- Python's audit hooks enforce filesystem boundaries
- `run_python` is disabled in strict mode

**Permission gates**: Tool execution can be configured per-tool via `TOOL_PERMISSIONS_JSON`:
- `allow`: Execute without prompting
- `prompt`: Ask user for approval
- `deny`: Block execution

**Shell command blocklist**: [main.py:436](main.py#L436) blocks dangerous commands (`rm -rf`, `sudo`, `shutdown`, etc.)

### Watchdog Architecture

Four-tier reliability design (partially implemented):

**Level 1 - KeepAlive**: PID tracking and automatic restart (✓ implemented)

**Level 2 - Watchdog**: Process monitoring with health checks (✓ implemented)
- HTTP health endpoint at `/health`
- Configurable failure threshold and grace period
- Exponential backoff for repeated crashes

**Level 3 - Guardian**: Pre-flight validation (⚠️ partial)
- Config validation exists
- Dependency checking optional (`CHECK_DEPENDENCIES_ON_START`)
- Port conflict detection not implemented

**Level 4 - Emergency Recovery**: LLM-based self-healing (❌ not implemented)

## Configuration

Configuration is loaded from `.env` in the project root. Key variables:

**API Settings**:
- `ANTHROPIC_API_KEY`: Claude API key (required)
- `CLAUDE_MODEL`: Model to use (default: `claude-sonnet-4-5-20250929`)
- `CLAUDE_MAX_TOKENS`: Max response tokens (default: 1024)

**Tool Execution**:
- `TOOL_WORKDIR`: Working directory for tool execution (default: `.`)
- `TOOL_TIMEOUT_SECONDS`: Timeout per tool execution (default: 300, max: 300)
- `CUSTOM_TOOL_DIR`: Directory containing custom tools (default: `tools`)
- `STRICT_WORKDIR_ONLY`: Enable workdir restrictions (default: 1)

**Scheduler**:
- `SCHEDULER_ENABLED`: Enable job scheduling (default: 1)
- `SCHEDULER_POLL_SECONDS`: Poll interval for scheduled jobs (default: 30)
- `SCHEDULE_FILE`: Path to schedule definitions (default: `schedules/jobs.json`)

**Permissions**:
- `TOOL_PERMISSIONS_JSON`: JSON object mapping tool names to permission levels
- `FORCE_TOOL_USE`: Force agent to always use tools (default: 0)
- `DRY_RUN`: Log tool calls without executing (default: 0)

**Logging**:
- `CHAT_LOG_FILE`: Path to conversation log (default: `logs/chat_log.jsonl`)
- `LOG_BASE_DIR`: Base directory for session logs when `SESSION_LOG_SPLIT=1`

**Watchdog** (for [watchdog_runner.py](watchdog_runner.py)):
- `WATCHDOG_RESTART_BACKOFF_SECONDS`: Initial backoff (default: 3)
- `WATCHDOG_MAX_BACKOFF_SECONDS`: Max backoff (default: 60)
- `WATCHDOG_MIN_UPTIME_SECONDS`: Minimum uptime to reset backoff (default: 20)
- `WATCHDOG_HEALTH_URL`: Health check endpoint (default: `http://127.0.0.1:8080/health`)
- `WATCHDOG_HEALTH_FAILURE_THRESHOLD`: Failures before restart (default: 3)

## Important Files

- **[implementation_checklist.md](implementation_checklist.md)** - Feature completion status and scoring
- **[insight.md](insight.md)** - Detailed implementation notes and design decisions
- **[policy.md](policy.md)** - Development principles
- **[prompt.md](prompt.md)** - System instruction template for tool creation
- **[style.md](style.md)** - Code style guidelines (Korean language preference)

## Testing Strategy

Tests are organized by component:

- `test_agent_core.py` - Core tool loading and execution
- `test_watchdog_runner.py` - Watchdog restart logic
- `test_modular_architecture.py` - Module integration tests
- `test_tool_specs.py` - Tool specification validation

TDD approach with cycle tracking:
- `tdd_cycles.py` runs test suite repeatedly
- Results logged to `logs/tdd_cycles.jsonl` with phase labels
- Supports labeled phases (e.g., `phase_modular_split`)

## Debugging

**View conversation log**:
```bash
tail -f logs/chat_log.jsonl | jq .
```

**View watchdog log**:
```bash
tail -f logs/watchdog.log
```

**Check tool execution events**:
```bash
jq 'select(.event == "tool_call" or .event == "tool_result")' logs/chat_log.jsonl
```

**Health check**:
```bash
curl http://127.0.0.1:8080/health
```

## Common Workflows

### Creating a New Tool

1. Read an existing tool as a template:
   ```
   tools/add_two_numbers.py를 읽어서 구조를 파악해줘
   ```

2. Create the new tool following the contract:
   - Define `TOOL_SPEC` with name, description, version, input_schema
   - Implement `run(input_data, context)` function
   - Add CLI entrypoint with argparse

3. Save to `tools/<toolname>.py`:
   ```
   /tool save_text_file {"file_path":"tools/my_tool.py","content":"..."}
   ```

4. Reload and test:
   ```
   /reload-tools
   /tool my_tool {"arg": "value"}
   ```

### Scheduling a Recurring Task

1. Create the tool (if it doesn't exist)
2. Test it manually first
3. Schedule it:
   ```
   /tool schedule_daily_tool {
     "tool_name": "my_tool",
     "time": "09:00",
     "tool_input": {"key": "value"}
   }
   ```
4. Verify schedule: `/schedules`

### Running in Production

For 24/7 operation:

1. Set `AGENT_MODE=daemon` in `.env`
2. Run with watchdog: `python3 watchdog_runner.py`
3. Use tmux/screen or install as system service (see `install_daemon.py`)
4. Monitor health: `curl http://127.0.0.1:8080/health`
5. Stop gracefully: `touch logs/watchdog.stop`

Logs will capture all tool executions and agent decisions.

## Notes for AI Assistants

- All user-facing messages should be in **Korean**
- The agent is designed to be **tool-first**: prefer creating/using tools over direct responses
- Tools are **stateless**: each execution is independent
- Chat history resets when `tools/*.py` changes to maintain consistency
- Built-in tools (`run_shell`, `read_file`, etc.) are defined in `main.py`, not in `tools/`
- Custom tools in `tools/` execute as subprocesses, not in-process imports

### Automatic Tool Detection for Common Questions

**CRITICAL**: When users ask about their activity, work, or what they did, **ALWAYS** use the `workday_recap` tool immediately. Do NOT ask for clarification - infer the mode from context.

**Trigger patterns** (즉시 workday_recap 도구 호출):

1. **Daily patterns** → `mode="daily"`:
   - 어제/오늘 뭐 했어?, 오늘 작업, 오늘 한 일
   - 오늘 뭐했나?, 오늘 활동, today, daily
   - 오늘 리포트, 오늘 정리, 오늘 요약

2. **Weekly patterns** → `mode="weekly"`:
   - 이번 주 뭐 했어?, 주간 리포트, 주간 정리
   - 이번주 작업, weekly, this week
   - 주간 요약, 7일간, 일주일

3. **Detail patterns** → add `include_diff=true`:
   - 코드 변경, diff, 상세, 자세히
   - 코드까지, 파일 내용, 변경사항
   - detailed, with code changes

4. **Timeline patterns** → (included by default):
   - 시간대별, 타임라인, 언제, when
   - 시간 분포, 피크 시간, 활동 시간

**Auto-detection rules**:
- If no time period mentioned → assume "daily"
- "어제" mentioned → use "daily" (covers yesterday)
- "지난주" mentioned → use "weekly"
- Multiple keywords → combine (e.g., "이번 주 코드까지" → weekly + diff)

**Example responses**:
```
User: "뭐 했어?"
→ Immediate call: workday_recap(mode="daily", scan_all_repos=true)
→ NO clarification questions

User: "오늘 작업 정리해줘"
→ Immediate call: workday_recap(mode="daily", scan_all_repos=true)

User: "이번 주 코드 변경까지 자세히"
→ Immediate call: workday_recap(mode="weekly", scan_all_repos=true, include_diff=true)

User: "지난주 뭐했나 시간대별로"
→ Immediate call: workday_recap(mode="weekly", scan_all_repos=true)
→ Timeline is automatically included
```

**Default parameters** (always use these unless user specifies otherwise):
- `scan_all_repos=true` (scan all Git repos in home directory)
- `include_diff=false` (unless user asks for code/diff/details)

**Output format**: Present the tool results in a clear, formatted Korean summary including:
- Git commits with messages and changed files
- Browser activity with page titles
- Shell command statistics
- Hourly timeline with peak hours
- Work pattern analysis (오전/오후/저녁/밤)

---

## Comprehensive Retrospective System

BoramClaw includes a transparent and powerful retrospective system that combines:
1. **Karpathy's 4 Principles** (Think, Simplicity, Surgical, Goal-Driven)
2. **Bitter Lesson** (Quality > Quantity, Learning Structure)
3. **Universal Prompt Collection** (Claude Code, Codex, Browser, Terminal)

### Core Tools

**1. Universal Prompt Collector** (`universal_prompt_collector.py`)
- Collects prompts from ALL sources:
  - Claude Code Desktop (~/.claude/projects/)
  - Codex (~/.codex/history.jsonl)
  - BoramClaw (logs/chat_log.jsonl)
  - Telegram (logs/telegram_bot.log)
  - Terminal AI tools (~/.zsh_history)
  - Browser History (Chrome SQLite)
  - log.md (manual curation)
- Runs daily at 20:00 (scheduled)
- Output: `logs/prompts_collected_YYYYMMDD.jsonl`

**2. Comprehensive Weekly Retrospective** (`comprehensive_weekly_retrospective.py`)
- Analyzes prompts + commits with Karpathy principles
- Generates quality scores (Karpathy 0-100, Bitter Lesson 0-100)
- Provides insights and next week SMART goals
- Runs weekly on Sundays at 21:00 (scheduled)
- Output: `weekly_retrospective_YYYY_weekWW.md`

### Usage

**Manual execution**:
```bash
# Collect all prompts (7 days)
python3 tools/universal_prompt_collector.py \
  --tool-input-json '{"days_back": 7, "sources": ["all"]}' \
  --tool-context-json '{"workdir": "/Users/boram/BoramClaw"}'

# Generate comprehensive retrospective
python3 tools/comprehensive_weekly_retrospective.py \
  --tool-input-json '{"days_back": 7}' \
  --tool-context-json '{"workdir": "/Users/boram/BoramClaw"}'
```

**Automatic scheduling**: Configured in `schedules/jobs.json`

**Key metrics tracked**:
- Total prompts by source (Claude Code, Codex, etc.)
- Karpathy principle scores (Think, Simplicity, Surgical, Goal-Driven)
- Prompt quality score (length, specificity, context)
- Git commit patterns (frequency, distribution, size)
- Next week SMART goals (measurable, specific)

### Retrospective Structure

The generated retrospective includes 6 parts:
1. **Raw Data**: Total transparency (prompts, commits, sources)
2. **Karpathy Analysis**: 4 principles with scores and advice
3. **Bitter Lesson**: Quality vs quantity, repeated patterns
4. **Pattern Insights**: Main tools, commit distribution, balance
5. **Next Week Goals**: SMART goals based on current metrics
6. **Action Checklist**: Executable tasks for improvement

This system ensures **complete transparency** in weekly retrospectives by capturing ALL prompts across ALL development tools, not just within BoramClaw.
