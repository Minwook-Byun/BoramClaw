#!/usr/bin/env python3
"""
Universal Prompt Collector - 전역에서 모든 프롬프트를 수집

데이터 소스:
1. Claude Code Desktop (~/.claude/projects/)
2. Codex (~/.codex/history.jsonl) ⭐ NEW!
3. BoramClaw (logs/chat_log.jsonl)
4. Telegram (logs/telegram_bot.log)
5. Terminal AI tools (~/.zsh_history)
6. Browser History (Chrome SQLite)
7. log.md (수동 큐레이션)

목표: 투명한 회고를 위한 완전한 프롬프트 히스토리
"""

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import sys

TOOL_SPEC = {
    "name": "universal_prompt_collector",
    "description": "전역에서 모든 프롬프트를 수집합니다 (Claude Code, BoramClaw, Telegram, Terminal 등)",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "days_back": {
                "type": "integer",
                "description": "며칠 전까지 수집할지",
                "default": 7
            },
            "sources": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["claude_code", "codex", "boramclaw", "telegram", "terminal", "browser", "log_md", "all"]
                },
                "description": "수집할 소스 목록 (기본: all)",
                "default": ["all"]
            },
            "min_length": {
                "type": "integer",
                "description": "최소 프롬프트 길이 (너무 짧은 건 제외)",
                "default": 5
            }
        }
    }
}


def collect_claude_code_prompts(days_back: int) -> List[Dict[str, Any]]:
    """Claude Code Desktop 프롬프트 수집"""
    prompts = []
    # timezone-aware로 변경
    from datetime import timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    # 모든 프로젝트 스캔
    claude_projects_dir = Path.home() / ".claude" / "projects"
    if not claude_projects_dir.exists():
        return prompts

    for project_dir in claude_projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        # JSONL 파일들 찾기
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            entry = json.loads(line)

                            # 사용자 메시지만 추출
                            if entry.get("type") == "user":
                                timestamp_str = entry.get("timestamp", "")
                                if timestamp_str:
                                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                                    if timestamp > cutoff:
                                        message_content = entry.get("message", {}).get("content", [])

                                        # 텍스트 추출
                                        text_parts = []
                                        for content in message_content:
                                            if isinstance(content, dict):
                                                if content.get("type") == "text":
                                                    text_parts.append(content.get("text", ""))
                                            elif isinstance(content, str):
                                                text_parts.append(content)

                                        full_text = "\n".join(text_parts).strip()

                                        # <ide_opened_file> 등 시스템 메시지 제외
                                        if full_text and not full_text.startswith("<"):
                                            prompts.append({
                                                "date": timestamp.strftime("%Y-%m-%d"),
                                                "time": timestamp.strftime("%H:%M:%S"),
                                                "content": full_text[:500],  # 처음 500자
                                                "full_content": full_text,
                                                "source": "claude_code",
                                                "project": project_dir.name
                                            })
                        except (json.JSONDecodeError, ValueError):
                            continue
            except Exception as e:
                print(f"Warning: {jsonl_file} 읽기 실패: {e}", file=sys.stderr)
                continue

    return prompts


def collect_boramclaw_prompts(days_back: int, workdir: str) -> List[Dict[str, Any]]:
    """BoramClaw 대화 로그에서 프롬프트 수집"""
    prompts = []
    cutoff = datetime.now().timestamp() - (days_back * 86400)

    chat_log_file = Path(workdir) / "logs" / "chat_log.jsonl"
    if not chat_log_file.exists():
        return prompts

    with open(chat_log_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line)

                if entry.get("role") == "user":
                    timestamp = entry.get("timestamp", 0)
                    if timestamp > cutoff:
                        content = entry.get("content", "")
                        if len(content) >= 5:
                            prompts.append({
                                "date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d"),
                                "time": datetime.fromtimestamp(timestamp).strftime("%H:%M:%S"),
                                "content": content[:500],
                                "full_content": content,
                                "source": "boramclaw"
                            })
            except (json.JSONDecodeError, ValueError):
                continue

    return prompts


def collect_telegram_prompts(days_back: int, workdir: str) -> List[Dict[str, Any]]:
    """Telegram 로그에서 프롬프트 수집"""
    prompts = []
    cutoff = datetime.now() - timedelta(days=days_back)

    telegram_log_file = Path(workdir) / "logs" / "telegram_bot.log"
    if not telegram_log_file.exists():
        return prompts

    # 패턴: [2026-02-18 21:00:00] INFO: 사용자 메시지: "오늘 뭐했어?"
    pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\].*사용자 메시지: "(.*)"'

    with open(telegram_log_file, 'r', encoding='utf-8') as f:
        for line in f:
            match = re.search(pattern, line)
            if match:
                timestamp_str, content = match.groups()
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    if timestamp > cutoff and len(content) >= 5:
                        prompts.append({
                            "date": timestamp_str[:10],
                            "time": timestamp_str[11:19],
                            "content": content,
                            "source": "telegram"
                        })
                except ValueError:
                    continue

    return prompts


def collect_terminal_ai_prompts(days_back: int) -> List[Dict[str, Any]]:
    """~/.zsh_history에서 AI 도구 명령어 수집"""
    prompts = []
    history_file = Path.home() / ".zsh_history"

    if not history_file.exists():
        return prompts

    ai_tools = ["codex", "aider", "continue", "cursor"]

    with open(history_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # EXTENDED_HISTORY 포맷: : 1234567890:0;command
            if line.startswith(':'):
                parts = line.split(';', 1)
                if len(parts) == 2:
                    command = parts[1].strip()

                    for tool in ai_tools:
                        if command.startswith(tool):
                            prompts.append({
                                "content": command,
                                "source": "terminal",
                                "tool": tool
                            })
                            break

    # 최근 50개만
    return prompts[-50:]


def collect_browser_prompts(days_back: int) -> List[Dict[str, Any]]:
    """Chrome 히스토리에서 AI 서비스 방문 기록 수집 (프롬프트 추론)"""
    prompts = []
    cutoff = datetime.now() - timedelta(days=days_back)

    # Chrome History DB
    chrome_history = Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "History"

    if not chrome_history.exists():
        return prompts

    # SQLite 복사 (원본은 잠금될 수 있음)
    import shutil
    temp_db = Path("/tmp/chrome_history_temp.db")
    try:
        shutil.copy(chrome_history, temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # AI 서비스 URL 필터
        ai_domains = ["chatgpt.com", "claude.ai", "perplexity.ai", "gemini.google.com"]

        # Chrome 시간 형식: WebKit/Chrome timestamp (1601-01-01 기준 microseconds)
        chrome_cutoff = int((cutoff.timestamp() + 11644473600) * 1000000)

        query = f"""
        SELECT url, title, last_visit_time
        FROM urls
        WHERE last_visit_time > {chrome_cutoff}
        AND ({' OR '.join([f"url LIKE '%{domain}%'" for domain in ai_domains])})
        ORDER BY last_visit_time DESC
        LIMIT 100
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        for url, title, last_visit_time in rows:
            # Chrome timestamp → Python datetime
            timestamp = datetime.fromtimestamp((last_visit_time / 1000000) - 11644473600)

            prompts.append({
                "date": timestamp.strftime("%Y-%m-%d"),
                "time": timestamp.strftime("%H:%M:%S"),
                "content": f"[브라우저] {title}",
                "url": url,
                "source": "browser"
            })

        conn.close()
        temp_db.unlink()
    except Exception as e:
        print(f"Warning: 브라우저 히스토리 읽기 실패: {e}", file=sys.stderr)
        if temp_db.exists():
            temp_db.unlink()

    return prompts


def collect_codex_prompts(days_back: int) -> List[Dict[str, Any]]:
    """Codex (~/.codex/history.jsonl) 프롬프트 수집"""
    prompts = []
    cutoff = datetime.now().timestamp() - (days_back * 86400)

    def _normalize_codex_text(raw: str) -> str:
        text = str(raw or "").strip()
        marker = "## My request for Codex:"
        if marker in text:
            text = text.split(marker, 1)[1].strip()
        # 노이즈성 인터럽트 메시지 제거
        if text.startswith("[Request interrupted"):
            return ""
        return text

    # history.jsonl (전체 히스토리)
    history_file = Path.home() / ".codex" / "history.jsonl"
    if history_file.exists():
        with open(history_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ts = entry.get("ts", 0)

                    if ts > cutoff:
                        text = _normalize_codex_text(entry.get("text", ""))
                        if len(text) >= 5:
                            prompts.append({
                                "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                                "time": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
                                "content": text[:500],
                                "full_content": text,
                                "source": "codex",
                                "session_id": entry.get("session_id", "")
                            })
                except (json.JSONDecodeError, ValueError):
                    continue

    # 세션별 rollout 파일들도 수집 (더 상세한 정보)
    sessions_dir = Path.home() / ".codex" / "sessions"
    if sessions_dir.exists():
        # 최근 7일 디렉토리만 스캔
        cutoff_date = datetime.now() - timedelta(days=days_back)

        for year_dir in sessions_dir.iterdir():
            if not year_dir.is_dir():
                continue
            for month_dir in year_dir.iterdir():
                if not month_dir.is_dir():
                    continue
                for day_dir in month_dir.iterdir():
                    if not day_dir.is_dir():
                        continue

                    # 날짜 체크
                    try:
                        dir_date = datetime.strptime(f"{year_dir.name}-{month_dir.name}-{day_dir.name}", "%Y-%m-%d")
                        if dir_date < cutoff_date:
                            continue
                    except ValueError:
                        continue

                    # rollout JSONL 파일들 읽기
                    for rollout_file in day_dir.glob("rollout-*.jsonl"):
                        try:
                            with open(rollout_file, 'r', encoding='utf-8') as f:
                                for line in f:
                                    try:
                                        entry = json.loads(line)

                                        # Codex rollout 포맷: type=event_msg, payload.type=user_message
                                        if entry.get("type") == "event_msg":
                                            payload = entry.get("payload", {})
                                            if isinstance(payload, dict) and payload.get("type") == "user_message":
                                                content = _normalize_codex_text(payload.get("message", ""))
                                                if len(content) < 5:
                                                    continue

                                                ts_raw = entry.get("timestamp", "")
                                                try:
                                                    dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                                                    ts = dt.timestamp()
                                                except Exception:
                                                    ts = 0.0

                                                if ts > cutoff:
                                                    prompts.append({
                                                        "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                                                        "time": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
                                                        "content": content[:500],
                                                        "full_content": content,
                                                        "source": "codex_session",
                                                        "session_file": rollout_file.name
                                                    })
                                    except (json.JSONDecodeError, ValueError):
                                        continue
                        except Exception:
                            continue

    # 중복 제거 (history + session 중복 대비)
    deduped = []
    seen = set()
    for p in prompts:
        key = (
            p.get("date", ""),
            p.get("time", ""),
            p.get("content", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    return deduped


def collect_log_md_prompts(workdir: str) -> List[Dict[str, Any]]:
    """log.md에서 수동 큐레이션된 프롬프트 수집"""
    prompts = []
    log_md = Path(workdir) / "log.md"

    if not log_md.exists():
        return prompts

    current_date = None
    current_title = None
    current_content = []

    with open(log_md, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip()

            if line.startswith('## ') and re.match(r'##\s+\d{4}-\d{2}-\d{2}', line):
                current_date = line[3:].strip()

            elif line.startswith('### 프롬프트:'):
                if current_title and current_content:
                    prompts.append({
                        "date": current_date,
                        "title": current_title,
                        "content": "\n".join(current_content).strip(),
                        "source": "log_md",
                        "curated": True  # 수동 큐레이션 마크
                    })

                current_title = line[13:].strip()
                current_content = []

            elif current_title and line and not line.startswith('#'):
                current_content.append(line)

        if current_title and current_content:
            prompts.append({
                "date": current_date,
                "title": current_title,
                "content": "\n".join(current_content).strip(),
                "source": "log_md",
                "curated": True
            })

    return prompts


def run(input_data: dict, context: dict) -> dict:
    """전역 프롬프트 수집 실행"""
    days_back = input_data.get("days_back", 7)
    sources = input_data.get("sources", ["all"])
    min_length = input_data.get("min_length", 5)
    workdir = context.get("workdir", ".")

    all_prompts = []

    # 소스별 수집
    if "all" in sources or "claude_code" in sources:
        all_prompts.extend(collect_claude_code_prompts(days_back))

    if "all" in sources or "codex" in sources:
        all_prompts.extend(collect_codex_prompts(days_back))

    if "all" in sources or "boramclaw" in sources:
        all_prompts.extend(collect_boramclaw_prompts(days_back, workdir))

    if "all" in sources or "telegram" in sources:
        all_prompts.extend(collect_telegram_prompts(days_back, workdir))

    if "all" in sources or "terminal" in sources:
        all_prompts.extend(collect_terminal_ai_prompts(days_back))

    if "all" in sources or "browser" in sources:
        all_prompts.extend(collect_browser_prompts(days_back))

    if "all" in sources or "log_md" in sources:
        all_prompts.extend(collect_log_md_prompts(workdir))

    # 길이 필터링
    filtered = [p for p in all_prompts if len(p.get("content", "")) >= min_length]

    # 날짜별 정렬
    filtered.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)

    # 통계
    by_source = {}
    for p in filtered:
        src = p.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    # 전체 저장 (회고용)
    output_file = Path(workdir) / "logs" / f"prompts_collected_{datetime.now().strftime('%Y%m%d')}.jsonl"
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        for p in filtered:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')

    return {
        "success": True,
        "total_prompts": len(filtered),
        "by_source": by_source,
        "date_range": f"{days_back}일",
        "output_file": str(output_file),
        "sample": filtered[:10]  # 최근 10개 샘플
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Universal Prompt Collector")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", type=str)
    parser.add_argument("--tool-context-json", type=str)

    args = parser.parse_args()

    if args.tool_spec_json:
        print(json.dumps(TOOL_SPEC, ensure_ascii=False, indent=2))
        sys.exit(0)

    input_data = json.loads(args.tool_input_json) if args.tool_input_json else {}
    context = json.loads(args.tool_context_json) if args.tool_context_json else {}

    result = run(input_data, context)
    print(json.dumps(result, ensure_ascii=False, indent=2))
