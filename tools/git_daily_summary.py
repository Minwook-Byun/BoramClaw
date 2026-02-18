from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "git_daily_summary",
    "description": "Git 커밋 히스토리를 분석하여 일일/주간 개발 활동을 요약합니다. 기본값은 오늘 커밋 요약.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Git 저장소 경로 (기본: 현재 워크디렉토리)",
            },
            "days": {
                "type": "integer",
                "description": "며칠 전까지 포함 (기본 1 = 오늘만)",
            },
            "author": {
                "type": "string",
                "description": "특정 작성자만 필터 (기본: 전체)",
            },
            "include_diff": {
                "type": "boolean",
                "description": "각 커밋의 실제 코드 변경 내역(diff)을 포함할지 여부 (기본: false)",
            },
        },
        "required": [],
    },
}


def _run_git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, timeout=30, cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git error: {result.stderr.strip()}")
    return result.stdout.strip()


def _get_commits(repo_path: str, days: int, author: str, include_diff: bool = False) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    git_args = [
        "log", f"--since={since}",
        "--pretty=format:%H|%an|%ae|%aI|%s",
        "--no-merges",
    ]
    if author:
        git_args.append(f"--author={author}")

    raw = _run_git(git_args, repo_path)
    if not raw:
        return []

    commits = []
    for line in raw.split("\n"):
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue

        commit_hash = parts[0]

        # 각 커밋의 변경 파일 목록 가져오기
        try:
            files_raw = _run_git(
                ["diff-tree", "--no-commit-id", "--name-status", "-r", commit_hash],
                repo_path
            )
            changed_files = []
            for file_line in files_raw.split("\n"):
                if file_line.strip():
                    parts_file = file_line.split("\t", 1)
                    if len(parts_file) == 2:
                        status = parts_file[0]  # A(추가), M(수정), D(삭제)
                        filepath = parts_file[1]
                        changed_files.append({"status": status, "file": filepath})
        except Exception:
            changed_files = []

        # include_diff가 True면 실제 diff도 가져오기
        diff_content = None
        if include_diff:
            try:
                # 간결한 diff (파일별 통계 + 일부 내용)
                diff_raw = _run_git(
                    ["show", "--stat", "--pretty=", commit_hash],
                    repo_path
                )
                diff_content = diff_raw[:3000]  # 최대 3000자
            except Exception:
                diff_content = None

        commit_data = {
            "hash": parts[0][:8],
            "author": parts[1],
            "email": parts[2],
            "date": parts[3],
            "message": parts[4],
            "files": changed_files,
        }
        if diff_content:
            commit_data["diff"] = diff_content

        commits.append(commit_data)
    return commits


def _get_diff_stats(repo_path: str, days: int) -> dict:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        raw = _run_git(
            ["log", f"--since={since}", "--no-merges", "--shortstat", "--pretty=format:"],
            repo_path,
        )
    except RuntimeError:
        return {"files_changed": 0, "insertions": 0, "deletions": 0}

    files, ins, dels = 0, 0, 0
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "file" in line:
            parts = line.split(",")
            for p in parts:
                p = p.strip()
                if "file" in p:
                    files += int(p.split()[0])
                elif "insertion" in p:
                    ins += int(p.split()[0])
                elif "deletion" in p:
                    dels += int(p.split()[0])

    return {"files_changed": files, "insertions": ins, "deletions": dels}


def _get_active_branches(repo_path: str, days: int) -> list[str]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        raw = _run_git(
            ["log", f"--since={since}", "--no-merges", "--pretty=format:%D"],
            repo_path,
        )
    except RuntimeError:
        return []

    branches = set()
    for line in raw.split("\n"):
        for ref in line.split(","):
            ref = ref.strip()
            if ref and "HEAD" not in ref and "->" not in ref:
                branches.add(ref)
    return sorted(branches)


def _time_distribution(commits: list[dict]) -> dict[str, int]:
    hours: dict[str, int] = {}
    for c in commits:
        try:
            dt = datetime.fromisoformat(c["date"])
            bucket = f"{dt.hour:02d}:00-{dt.hour:02d}:59"
            hours[bucket] = hours.get(bucket, 0) + 1
        except (ValueError, KeyError):
            pass
    return dict(sorted(hours.items()))


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    repo_path = input_data.get("repo_path", context.get("workdir", "."))
    days = input_data.get("days", 1)
    author = input_data.get("author", "")
    include_diff = input_data.get("include_diff", False)

    # git repo인지 확인
    try:
        _run_git(["rev-parse", "--git-dir"], repo_path)
    except (RuntimeError, FileNotFoundError):
        return {"ok": False, "error": f"{repo_path}는 git 저장소가 아닙니다."}

    commits = _get_commits(repo_path, days, author, include_diff)
    stats = _get_diff_stats(repo_path, days)
    branches = _get_active_branches(repo_path, days)
    time_dist = _time_distribution(commits)

    repo_name = os.path.basename(os.path.abspath(repo_path))

    return {
        "ok": True,
        "repo": repo_name,
        "period": f"최근 {days}일",
        "commit_count": len(commits),
        "commits": commits[:30],  # 최대 30개
        "stats": stats,
        "active_branches": branches,
        "time_distribution": time_dist,
        "summary_hint": (
            f"{repo_name}: {len(commits)}건 커밋, "
            f"+{stats['insertions']}/-{stats['deletions']} "
            f"({stats['files_changed']} files)"
        ),
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="git_daily_summary cli")
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
