from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from session_timeseries import load_timeseries_rows
from turn_feedback import summarize_turn_feedback


def _local_now(now: datetime | None = None) -> datetime:
    base = now or datetime.now().astimezone()
    if base.tzinfo is None:
        return base.astimezone()
    return base.astimezone()


def _day_start(day: date, now: datetime) -> datetime:
    return datetime.combine(day, time.min, tzinfo=now.tzinfo)


def _load_prompt_rows(history_file: Path, *, target_date: date) -> list[dict[str, Any]]:
    if not history_file.exists():
        return []

    rows: list[dict[str, Any]] = []
    with history_file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            ts_raw = row.get("ts")
            if not isinstance(ts_raw, (int, float)):
                continue
            local_ts = datetime.fromtimestamp(float(ts_raw)).astimezone()
            if local_ts.date() != target_date:
                continue
            prompt = str(row.get("text", "")).strip()
            if not prompt:
                continue
            rows.append(
                {
                    "session_id": str(row.get("session_id", "")).strip(),
                    "ts": local_ts.isoformat(),
                    "text": prompt,
                }
            )
    return rows


def _run_git(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _repo_root(candidate: Path) -> Path | None:
    target = candidate.resolve()
    if target.is_file():
        target = target.parent
    stdout = _run_git(["rev-parse", "--show-toplevel"], cwd=target)
    if not stdout:
        return None
    root = Path(stdout.strip()).expanduser()
    if not root.exists():
        return None
    return root.resolve()


def _parse_status_lines(lines: list[str]) -> tuple[int, int, int, list[str]]:
    staged = 0
    modified = 0
    untracked = 0
    changed_files: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line or line.startswith("## "):
            continue
        if line.startswith("?? "):
            untracked += 1
            changed_files.append(line[3:].strip())
            continue
        if len(line) < 4:
            continue
        x = line[0]
        y = line[1]
        file_part = line[3:].strip()
        if "->" in file_part:
            file_part = file_part.split("->", 1)[1].strip()
        changed_files.append(file_part)
        if x not in {" ", "?"}:
            staged += 1
        if y not in {" ", "?"} or x in {"M", "A", "R", "C", "D"}:
            modified += 1

    deduped_files = list(dict.fromkeys(item for item in changed_files if item))
    return staged, modified, untracked, deduped_files


def _probe_repo(repo_root: Path, *, since: datetime) -> dict[str, Any]:
    branch = _run_git(["branch", "--show-current"], cwd=repo_root) or "-"
    status_text = _run_git(["status", "--short", "--branch"], cwd=repo_root)
    status_lines = status_text.splitlines() if status_text else []
    staged, modified, untracked, changed_files = _parse_status_lines(status_lines)

    commits_text = _run_git(
        ["log", f"--since={since.isoformat()}", "--pretty=format:%h\t%s\t%cI", "--max-count=5"],
        cwd=repo_root,
    )
    recent_commits: list[dict[str, str]] = []
    if commits_text:
        for line in commits_text.splitlines():
            sha, _, remainder = line.partition("\t")
            subject, _, committed_at = remainder.partition("\t")
            recent_commits.append(
                {
                    "sha": sha.strip(),
                    "subject": subject.strip(),
                    "committed_at": committed_at.strip(),
                }
            )

    return {
        "name": repo_root.name,
        "path": str(repo_root),
        "branch": branch.strip() or "-",
        "staged_files": staged,
        "modified_files": modified,
        "untracked_files": untracked,
        "changed_files": changed_files[:8],
        "recent_commits": recent_commits,
    }


def _candidate_workdirs(*, workdir: Path, rows: list[dict[str, Any]], limit: int) -> list[str]:
    counts: Counter[str] = Counter()
    counts[str(workdir.resolve())] += 1000
    for row in rows:
        for item in row.get("top_workdirs", []) or []:
            if not isinstance(item, dict):
                continue
            workdir_value = str(item.get("workdir", "")).strip()
            if not workdir_value:
                continue
            counts[workdir_value] += int(item.get("count", 0) or 0) or 1
    return [value for value, _ in counts.most_common(limit)]


def collect_wrapup_evidence(
    *,
    workdir: str | Path,
    session_memory: list[str] | None = None,
    timeseries_file: str | Path | None = None,
    history_file: str | Path | None = None,
    now: datetime | None = None,
    max_prompts: int = 8,
    max_repos: int = 5,
    max_workdirs: int = 8,
) -> dict[str, Any]:
    local_now = _local_now(now)
    today = local_now.date()
    today_start = _day_start(today, local_now)

    workdir_path = Path(workdir).expanduser().resolve()
    history_path = Path(history_file or (Path.home() / ".codex" / "history.jsonl")).expanduser().resolve()
    prompt_rows = _load_prompt_rows(history_path, target_date=today)

    timeseries_path = Path(timeseries_file).expanduser().resolve() if timeseries_file else None
    rollout_rows: list[dict[str, Any]] = []
    if timeseries_path is not None and timeseries_path.exists():
        rollout_rows = load_timeseries_rows(
            timeseries_path,
            start_date=today.isoformat(),
            end_date=today.isoformat(),
            kinds=["codex_rollout"],
        )

    repo_paths: list[Path] = []
    for item in _candidate_workdirs(workdir=workdir_path, rows=rollout_rows, limit=max_workdirs):
        repo_root = _repo_root(Path(item))
        if repo_root is None:
            continue
        if repo_root in repo_paths:
            continue
        repo_paths.append(repo_root)
        if len(repo_paths) >= max_repos:
            break

    touched_repos = [_probe_repo(repo_root, since=today_start) for repo_root in repo_paths]
    git_totals = {
        "repo_count": len(touched_repos),
        "staged_files": sum(int(repo.get("staged_files", 0) or 0) for repo in touched_repos),
        "modified_files": sum(int(repo.get("modified_files", 0) or 0) for repo in touched_repos),
        "untracked_files": sum(int(repo.get("untracked_files", 0) or 0) for repo in touched_repos),
        "commit_count": sum(len(repo.get("recent_commits", []) or []) for repo in touched_repos),
    }

    memory_tail = [str(item).strip()[:220] for item in (session_memory or []) if str(item).strip()][-8:]
    prompt_samples = [row["text"][:220] for row in prompt_rows[:max_prompts]]
    prompt_session_ids = list(dict.fromkeys(row["session_id"] for row in prompt_rows if row.get("session_id")))[:8]
    feedback_summary = summarize_turn_feedback(prompt_rows)

    return {
        "date": today.isoformat(),
        "collected_at": local_now.isoformat(),
        "history_file": str(history_path),
        "prompt_count": len(prompt_rows),
        "prompt_samples": prompt_samples,
        "prompt_session_ids": prompt_session_ids,
        "feedback_prompt_count": int(feedback_summary.get("feedback_prompt_count", 0) or 0),
        "feedback_counts": feedback_summary.get("feedback_counts", {}),
        "feedback_rates": feedback_summary.get("feedback_rates", {}),
        "top_correction_hints": feedback_summary.get("top_correction_hints", []),
        "recent_feedback": feedback_summary.get("recent_feedback", []),
        "session_memory_tail": memory_tail,
        "active_workdirs": _candidate_workdirs(workdir=workdir_path, rows=rollout_rows, limit=max_workdirs),
        "rollout_count": len(rollout_rows),
        "touched_repos": touched_repos,
        "repo_names": [repo.get("name", "") for repo in touched_repos if str(repo.get("name", "")).strip()],
        "git_totals": git_totals,
    }


def render_wrapup_fallback(*, evidence: dict[str, Any], focus: str = "") -> str:
    prompt_samples = [str(item).strip() for item in evidence.get("prompt_samples", []) if str(item).strip()]
    touched_repos = [repo for repo in evidence.get("touched_repos", []) if isinstance(repo, dict)]
    git_totals = evidence.get("git_totals", {}) or {}
    feedback_counts = evidence.get("feedback_counts", {}) if isinstance(evidence.get("feedback_counts", {}), dict) else {}
    top_correction_hints = [item for item in evidence.get("top_correction_hints", []) if isinstance(item, dict)]
    recent_feedback = [item for item in evidence.get("recent_feedback", []) if isinstance(item, dict)]

    lines = ["## 오늘 실제로 한 일"]
    if touched_repos:
        for repo in touched_repos[:4]:
            files = ", ".join(repo.get("changed_files", [])[:4]) or "파일 근거 없음"
            lines.append(
                f"- {repo.get('name', '-')}: 브랜치 {repo.get('branch', '-')}, 변경 파일 {files}"
            )
    else:
        lines.append("- 로컬 Git 증거가 부족해 오늘 작업 레포를 확정하지 못했습니다.")

    lines.append("")
    lines.append("## 프롬프트 흐름 해석")
    if prompt_samples:
        for sample in prompt_samples[:4]:
            lines.append(f"- {sample}")
    else:
        lines.append("- 오늘 기록된 Codex 프롬프트가 아직 없습니다.")
    if any(int(feedback_counts.get(key, 0) or 0) > 0 for key in ("accepted", "corrected", "retried")):
        lines.append(
            "- next-state 신호: "
            f"accepted {int(feedback_counts.get('accepted', 0) or 0)}, "
            f"corrected {int(feedback_counts.get('corrected', 0) or 0)}, "
            f"retried {int(feedback_counts.get('retried', 0) or 0)}, "
            f"ambiguous {int(feedback_counts.get('ambiguous', 0) or 0)}"
        )
    for item in top_correction_hints[:4]:
        label = str(item.get("label", "")).strip()
        count = int(item.get("count", 0) or 0)
        if label and count > 0:
            lines.append(f"- 교정 힌트: {label} ({count})")

    lines.append("")
    lines.append("## 남은 일 / 리스크")
    lines.append(
        "- 변경사항은 존재하지만 자동 fallback이므로 우선순위 판단은 제한적입니다. 실제 diff와 테스트를 확인해 마감 상태를 확정해야 합니다."
    )
    if recent_feedback:
        latest = recent_feedback[-1]
        lines.append(
            "- 최근 사용자 반응: "
            f"{str(latest.get('outcome', 'ambiguous')).strip()} · {str(latest.get('text', '')).strip()[:120]}"
        )
    lines.append(
        f"- 현재 추정 Git 상태: modified {int(git_totals.get('modified_files', 0) or 0)}, "
        f"untracked {int(git_totals.get('untracked_files', 0) or 0)}, commits {int(git_totals.get('commit_count', 0) or 0)}"
    )

    lines.append("")
    lines.append("## 다음 세션 첫 액션")
    if focus.strip():
        lines.append(f"1. {focus.strip()} 기준으로 가장 영향도 큰 레포부터 `git status`와 핵심 diff를 재확인합니다.")
    else:
        lines.append("1. 가장 영향도 큰 레포부터 `git status`와 핵심 diff를 재확인합니다.")
    if touched_repos:
        first_repo = touched_repos[0]
        lines.append(f"2. `{first_repo.get('path', '.')}` 에서 변경 파일과 미완료 테스트를 먼저 정리합니다.")
    else:
        lines.append("2. 오늘 프롬프트와 로컬 수정 흔적을 대조해 실제 완료/미완료를 분리합니다.")
    lines.append("3. 회고를 업데이트하기 전에 근거가 되는 파일, 프롬프트, 커밋을 다시 수집합니다.")
    return "\n".join(lines).strip()
