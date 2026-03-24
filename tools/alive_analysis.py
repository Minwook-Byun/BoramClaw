#!/usr/bin/env python3
"""
alive_analysis.py — ALIVE 분석 루프 도구

BoramClaw 커스텀 도구로서 ALIVE 루프(ASK→LOOK→INVESTIGATE→VOICE→EVOLVE)를
vault/analyses/ 디렉토리에 마크다운으로 기록한다.
Obsidian wiki-link로 분석 간 연결을 지원한다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "alive_analysis",
    "description": (
        "ALIVE 분석 루프를 실행합니다 (ASK→LOOK→INVESTIGATE→VOICE→EVOLVE).\n"
        "- '분석 시작', '새 분석', 'analysis' 등의 요청에 응답\n"
        "- new: 새 분석 생성 / next: 다음 단계 진행 / status: 진행률 확인\n"
        "- search: 과거 분석 검색 / list: 분석 목록 / archive: 완료 보관"
    ),
    "version": __version__,
    "network_access": False,
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["new", "next", "status", "search", "archive", "list"],
                "description": "실행할 분석 명령",
            },
            "analysis_id": {
                "type": "string",
                "description": "대상 분석 ID (예: F-2026-0324-001)",
            },
            "analysis_type": {
                "type": "string",
                "enum": ["full", "quick", "experiment"],
                "description": "분석 유형 (기본값: full)",
            },
            "title": {
                "type": "string",
                "description": "새 분석 제목 (new 명령에서 사용)",
            },
            "query": {
                "type": "string",
                "description": "검색어 (search 명령에서 사용)",
            },
            "content": {
                "type": "string",
                "description": "현재 단계에 기록할 내용 (next 명령에서 사용)",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "분석 태그 (new 명령에서 사용)",
            },
        },
        "required": ["command"],
    },
}

# ── Constants ──

VAULT_SUBDIR = "vault"
ANALYSES_SUBDIR = "analyses"
ACTIVE_DIR = "active"
ARCHIVE_DIR = "archive"

STAGES = [
    ("01_ask", "ASK", "What do we want to know — and why?"),
    ("02_look", "LOOK", "What does the data actually show?"),
    ("03_investigate", "INVESTIGATE", "Why is it really happening?"),
    ("04_voice", "VOICE", "So what — and now what?"),
    ("05_evolve", "EVOLVE", "What would change the conclusion?"),
]

TYPE_PREFIX = {"full": "F", "quick": "Q", "experiment": "E"}

KST = timezone(timedelta(hours=9))


# ── Helpers ──

def _now_kst() -> datetime:
    return datetime.now(KST)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9가-힣]+", "-", text.strip().lower())
    return slug.strip("-")[:40]


def _resolve_vault(workdir: Path) -> Path:
    return (workdir / VAULT_SUBDIR).resolve()


def _resolve_analyses(workdir: Path) -> Path:
    return _resolve_vault(workdir) / ANALYSES_SUBDIR


def _next_seq(active_dir: Path, prefix: str, date_str: str) -> int:
    pattern = f"{prefix}-{date_str}-"
    existing = [
        d.name for d in active_dir.iterdir()
        if d.is_dir() and d.name.startswith(pattern)
    ] if active_dir.exists() else []
    if not existing:
        return 1
    nums = []
    for name in existing:
        # F-2026-0324-001_slug → extract 001
        match = re.match(rf"{re.escape(pattern)}(\d+)", name)
        if match:
            nums.append(int(match.group(1)))
    return max(nums, default=0) + 1


def _read_meta(analysis_dir: Path) -> dict[str, Any]:
    meta_path = analysis_dir / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def _write_meta(analysis_dir: Path, meta: dict[str, Any]) -> None:
    meta_path = analysis_dir / "meta.json"
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _current_stage_index(analysis_dir: Path) -> int:
    """Return the index of the last completed stage (0-based), or -1 if none."""
    for i in range(len(STAGES) - 1, -1, -1):
        stage_file = analysis_dir / f"{STAGES[i][0]}.md"
        if stage_file.exists():
            return i
    return -1


def _find_analysis_dir(analyses_path: Path, analysis_id: str) -> Path | None:
    """Find the analysis directory by ID prefix."""
    for subdir in [ACTIVE_DIR, ARCHIVE_DIR]:
        parent = analyses_path / subdir
        if not parent.exists():
            continue
        for d in parent.iterdir():
            if d.is_dir() and d.name.startswith(analysis_id):
                return d
    return None


# ── Commands ──

def cmd_new(input_data: dict[str, Any], analyses_path: Path) -> dict[str, Any]:
    analysis_type = input_data.get("analysis_type", "full")
    title = input_data.get("title", "untitled")
    tags = input_data.get("tags", [])
    content = input_data.get("content", "")

    now = _now_kst()
    prefix = TYPE_PREFIX.get(analysis_type, "F")
    date_str = now.strftime("%Y-%m%d")
    seq = _next_seq(analyses_path / ACTIVE_DIR, prefix, date_str)
    analysis_id = f"{prefix}-{date_str}-{seq:03d}"
    slug = _slugify(title)

    active_dir = analyses_path / ACTIVE_DIR

    if analysis_type == "quick":
        # Quick: single file
        filename = f"quick_{analysis_id}_{slug}.md"
        filepath = active_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        md = f"# {analysis_id}: {title}\n\n"
        md += f"**유형**: Quick | **생성**: {now.strftime('%Y-%m-%d %H:%M')} | **태그**: {', '.join(tags)}\n\n"
        md += "---\n\n"
        md += "## ASK\n\n"
        md += f"{content}\n\n" if content else "_질문을 작성하세요._\n\n"
        md += "## LOOK\n\n\n## INVESTIGATE\n\n\n## VOICE\n\n\n## EVOLVE\n\n"
        filepath.write_text(md, encoding="utf-8")

        return {
            "ok": True,
            "analysis_id": analysis_id,
            "type": "quick",
            "file": str(filepath),
            "title": title,
        }
    else:
        # Full or Experiment: directory with stage files
        dir_name = f"{analysis_id}_{slug}"
        analysis_dir = active_dir / dir_name
        analysis_dir.mkdir(parents=True, exist_ok=True)

        # meta.json
        meta = {
            "id": analysis_id,
            "title": title,
            "type": analysis_type,
            "created": now.isoformat(),
            "analyst": "MYSC AX",
            "tags": tags,
            "current_stage": 0,
        }
        _write_meta(analysis_dir, meta)

        # 01_ask.md
        ask_md = f"# {STAGES[0][1]} — {title}\n\n"
        ask_md += f"**분석 ID**: [[{analysis_id}]] | **생성**: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        ask_md += "---\n\n"
        ask_md += "## 핵심 질문\n\n"
        ask_md += f"{content}\n\n" if content else "_무엇을 알고 싶은가? 왜 중요한가?_\n\n"
        ask_md += "## 가설\n\n\n## 범위\n\n\n## 성공 기준\n\n"
        (analysis_dir / "01_ask.md").write_text(ask_md, encoding="utf-8")

        return {
            "ok": True,
            "analysis_id": analysis_id,
            "type": analysis_type,
            "directory": str(analysis_dir),
            "title": title,
            "stage": "01_ask",
        }


def cmd_next(input_data: dict[str, Any], analyses_path: Path) -> dict[str, Any]:
    analysis_id = input_data.get("analysis_id", "")
    content = input_data.get("content", "")

    if not analysis_id:
        return {"ok": False, "error": "analysis_id가 필요합니다."}

    analysis_dir = _find_analysis_dir(analyses_path, analysis_id)
    if not analysis_dir:
        return {"ok": False, "error": f"분석 '{analysis_id}'을 찾을 수 없습니다."}

    current_idx = _current_stage_index(analysis_dir)
    next_idx = current_idx + 1

    if next_idx >= len(STAGES):
        return {
            "ok": False,
            "error": "모든 단계가 완료됐습니다. archive 명령으로 보관하세요.",
            "analysis_id": analysis_id,
        }

    stage_file, stage_name, stage_question = STAGES[next_idx]
    now = _now_kst()

    md = f"# {stage_name} — {analysis_id}\n\n"
    md += f"**단계**: {next_idx + 1}/5 | **작성**: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
    md += f"> {stage_question}\n\n"
    md += "---\n\n"
    md += f"{content}\n" if content else "_내용을 작성하세요._\n"

    filepath = analysis_dir / f"{stage_file}.md"
    filepath.write_text(md, encoding="utf-8")

    # Update meta
    meta = _read_meta(analysis_dir)
    meta["current_stage"] = next_idx
    meta[f"{stage_name.lower()}_at"] = now.isoformat()
    _write_meta(analysis_dir, meta)

    return {
        "ok": True,
        "analysis_id": analysis_id,
        "stage": stage_file,
        "stage_name": stage_name,
        "stage_number": f"{next_idx + 1}/5",
        "file": str(filepath),
    }


def cmd_status(input_data: dict[str, Any], analyses_path: Path) -> dict[str, Any]:
    analysis_id = input_data.get("analysis_id", "")

    if not analysis_id:
        return {"ok": False, "error": "analysis_id가 필요합니다."}

    analysis_dir = _find_analysis_dir(analyses_path, analysis_id)
    if not analysis_dir:
        return {"ok": False, "error": f"분석 '{analysis_id}'을 찾을 수 없습니다."}

    meta = _read_meta(analysis_dir)
    current_idx = _current_stage_index(analysis_dir)

    completed_stages = []
    pending_stages = []
    for i, (stage_file, stage_name, _) in enumerate(STAGES):
        if (analysis_dir / f"{stage_file}.md").exists():
            completed_stages.append(stage_name)
        else:
            pending_stages.append(stage_name)

    progress = len(completed_stages) / len(STAGES) * 100

    return {
        "ok": True,
        "analysis_id": analysis_id,
        "title": meta.get("title", ""),
        "type": meta.get("type", ""),
        "progress": f"{progress:.0f}%",
        "completed": completed_stages,
        "pending": pending_stages,
        "current_stage": STAGES[current_idx][1] if current_idx >= 0 else "없음",
        "next_stage": STAGES[current_idx + 1][1] if current_idx + 1 < len(STAGES) else "완료",
    }


def cmd_search(input_data: dict[str, Any], analyses_path: Path) -> dict[str, Any]:
    query = input_data.get("query", "").strip()
    if not query:
        return {"ok": False, "error": "query가 필요합니다."}

    query_lower = query.lower()
    results = []

    for md_file in analyses_path.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if query_lower in text.lower():
            # Extract context lines
            lines = text.splitlines()
            matches = [
                line.strip() for line in lines
                if query_lower in line.lower()
            ][:3]
            results.append({
                "file": str(md_file.relative_to(analyses_path)),
                "matches": matches,
            })

    return {
        "ok": True,
        "query": query,
        "total": len(results),
        "results": results[:20],
    }


def cmd_list(input_data: dict[str, Any], analyses_path: Path) -> dict[str, Any]:
    items = []

    for subdir, status in [(ACTIVE_DIR, "active"), (ARCHIVE_DIR, "archived")]:
        parent = analyses_path / subdir
        if not parent.exists():
            continue
        for entry in sorted(parent.iterdir()):
            if entry.is_dir():
                meta = _read_meta(entry)
                current_idx = _current_stage_index(entry)
                progress = (current_idx + 1) / len(STAGES) * 100 if current_idx >= 0 else 0
                items.append({
                    "id": meta.get("id", entry.name),
                    "title": meta.get("title", ""),
                    "type": meta.get("type", ""),
                    "status": status,
                    "progress": f"{progress:.0f}%",
                    "created": meta.get("created", ""),
                    "tags": meta.get("tags", []),
                })
            elif entry.is_file() and entry.name.startswith("quick_"):
                # Quick analysis (single file)
                name = entry.stem
                match = re.match(r"quick_(Q-\d{4}-\d{4}-\d{3})_(.*)", name)
                aid = match.group(1) if match else name
                slug = match.group(2) if match else ""
                items.append({
                    "id": aid,
                    "title": slug.replace("-", " "),
                    "type": "quick",
                    "status": status,
                    "progress": "N/A",
                    "created": "",
                    "tags": [],
                })

    return {
        "ok": True,
        "total": len(items),
        "analyses": items,
    }


def cmd_archive(input_data: dict[str, Any], analyses_path: Path) -> dict[str, Any]:
    analysis_id = input_data.get("analysis_id", "")
    if not analysis_id:
        return {"ok": False, "error": "analysis_id가 필요합니다."}

    # Search in active only
    active_path = analyses_path / ACTIVE_DIR
    source = None
    if active_path.exists():
        for entry in active_path.iterdir():
            if entry.name.startswith(analysis_id):
                source = entry
                break

    # Also check quick analysis files
    if not source and active_path.exists():
        for entry in active_path.iterdir():
            if entry.is_file() and analysis_id in entry.name:
                source = entry
                break

    if not source:
        return {"ok": False, "error": f"active에서 '{analysis_id}'을 찾을 수 없습니다."}

    archive_path = analyses_path / ARCHIVE_DIR
    archive_path.mkdir(parents=True, exist_ok=True)
    dest = archive_path / source.name
    shutil.move(str(source), str(dest))

    # Update meta
    if dest.is_dir():
        meta = _read_meta(dest)
        meta["archived_at"] = _now_kst().isoformat()
        meta["status"] = "archived"
        _write_meta(dest, meta)

    return {
        "ok": True,
        "analysis_id": analysis_id,
        "moved_from": str(source),
        "moved_to": str(dest),
    }


# ── Entry ──

COMMANDS = {
    "new": cmd_new,
    "next": cmd_next,
    "status": cmd_status,
    "search": cmd_search,
    "list": cmd_list,
    "archive": cmd_archive,
}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    command = input_data.get("command", "")
    if command not in COMMANDS:
        return {"ok": False, "error": f"알 수 없는 명령: {command}. 사용 가능: {list(COMMANDS.keys())}"}

    workdir = Path(context.get("workdir", ".")).expanduser().resolve()
    analyses_path = _resolve_analyses(workdir)

    return COMMANDS[command](input_data, analyses_path)


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=TOOL_SPEC["description"])
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
        result = run(input_data=input_data, context=context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
