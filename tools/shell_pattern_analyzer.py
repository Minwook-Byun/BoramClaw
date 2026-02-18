from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "shell_pattern_analyzer",
    "description": "셸 히스토리(~/.zsh_history)를 분석하여 명령어 패턴, 자주 쓰는 명령어, alias 추천 등을 제공합니다.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "분석할 기간 (일 단위, 기본 7일)",
            },
            "top_n": {
                "type": "integer",
                "description": "상위 N개 명령어 (기본 15)",
            },
            "history_file": {
                "type": "string",
                "description": "히스토리 파일 경로 (기본: ~/.zsh_history)",
            },
        },
        "required": [],
    },
}

# extended history format: `: 1708290000:0;command`
_ZSH_EXTENDED_RE = re.compile(r"^:\s*(\d+):\d+;(.+)$")


def _parse_zsh_history(path: str, since_ts: float) -> list[dict]:
    """zsh 히스토리 파일을 파싱합니다.

    EXTENDED_HISTORY 포맷 (`: timestamp:0;command`)과
    일반 포맷 (줄마다 명령어만) 모두 지원합니다.
    """
    entries = []
    filepath = Path(path).expanduser()
    if not filepath.exists():
        return entries

    try:
        raw = filepath.read_bytes()
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return entries

    has_extended = False
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = _ZSH_EXTENDED_RE.match(line)
        if m:
            has_extended = True
            ts = float(m.group(1))
            cmd = m.group(2).strip()
            if ts >= since_ts:
                entries.append({"timestamp": ts, "command": cmd})
        elif has_extended and entries:
            # 여러 줄 명령어의 연속 (extended mode)
            entries[-1]["command"] += "\n" + line

    # extended 포맷이 아닌 경우: 타임스탬프 없이 전부 수집
    if not has_extended:
        now_ts = datetime.now().timestamp()
        for line in lines:
            line = line.strip()
            if line:
                entries.append({"timestamp": now_ts, "command": line})

    return entries


def _extract_base_command(cmd: str) -> str:
    """명령어에서 기본 커맨드만 추출."""
    cmd = cmd.strip()
    # 파이프 이전만
    cmd = cmd.split("|")[0].strip()
    # sudo 제거
    if cmd.startswith("sudo "):
        cmd = cmd[5:].strip()
    # 첫 단어
    parts = cmd.split()
    return parts[0] if parts else cmd


def _suggest_aliases(freq: list[tuple[str, int]]) -> list[dict]:
    """자주 쓰는 긴 명령어에 대해 alias 추천."""
    suggestions = []
    for cmd, count in freq:
        if count >= 3 and len(cmd) > 15:
            # 간단한 축약 생성
            words = cmd.split()
            if len(words) >= 2:
                short = "".join(w[0] for w in words[:3])
                suggestions.append({
                    "command": cmd,
                    "count": count,
                    "suggested_alias": short,
                    "definition": f'alias {short}="{cmd}"',
                })
    return suggestions[:5]


def _detect_repetitive_sequences(entries: list[dict], min_repeat: int = 3) -> list[dict]:
    """같은 명령어 시퀀스가 반복되는 패턴 감지."""
    if len(entries) < 6:
        return []

    commands = [e["command"].strip() for e in entries]
    sequences = []

    # 2-4개 명령어 시퀀스 탐색
    for seq_len in range(2, 5):
        seq_counter: Counter = Counter()
        for i in range(len(commands) - seq_len + 1):
            seq = tuple(commands[i:i + seq_len])
            seq_counter[seq] += 1

        for seq, count in seq_counter.most_common(3):
            if count >= min_repeat:
                sequences.append({
                    "sequence": list(seq),
                    "count": count,
                    "suggestion": "이 시퀀스를 스크립트로 만드는 것을 추천합니다.",
                })

    return sequences[:3]


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    days = input_data.get("days", 7)
    top_n = input_data.get("top_n", 15)
    history_file = input_data.get("history_file", "~/.zsh_history")

    since = datetime.now() - timedelta(days=days)
    since_ts = since.timestamp()

    entries = _parse_zsh_history(history_file, since_ts)

    if not entries:
        return {
            "ok": True,
            "period": f"최근 {days}일",
            "total_commands": 0,
            "message": "해당 기간에 셸 히스토리가 없습니다.",
        }

    # 기본 명령어 빈도
    base_cmds = Counter(_extract_base_command(e["command"]) for e in entries)
    top_commands = base_cmds.most_common(top_n)

    # 전체 명령어 빈도 (alias 추천용)
    full_cmds = Counter(e["command"].strip() for e in entries)
    top_full = full_cmds.most_common(30)

    # 시간대별 분포
    hour_dist: Counter = Counter()
    for e in entries:
        h = datetime.fromtimestamp(e["timestamp"]).hour
        hour_dist[f"{h:02d}:00"] += 1
    time_distribution = dict(sorted(hour_dist.items()))

    # alias 추천
    alias_suggestions = _suggest_aliases(top_full)

    # 반복 시퀀스 감지
    repetitive = _detect_repetitive_sequences(entries)

    return {
        "ok": True,
        "period": f"최근 {days}일",
        "total_commands": len(entries),
        "unique_commands": len(full_cmds),
        "top_commands": [{"command": c, "count": n} for c, n in top_commands],
        "time_distribution": time_distribution,
        "alias_suggestions": alias_suggestions,
        "repetitive_sequences": repetitive,
        "most_active_hour": max(hour_dist, key=hour_dist.get) if hour_dist else "N/A",
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="shell_pattern_analyzer cli")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()

    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0

        input_data = _load_json_object(args.tool_input_json)
        context = _load_json_object(args.tool_context_json)
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
