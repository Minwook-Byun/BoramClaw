from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from session_timeseries import collect_codex_rollout_snapshots, load_timeseries_rows, summarize_period
from turn_feedback import summarize_turn_feedback

DELIVERY_CATEGORIES = {"source_code", "test", "docs_config"}
CONFIG_FILENAMES = {
    ".env",
    ".env.example",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "bun.lock",
    "bun.lockb",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.ts",
    "next.config.js",
    "next.config.mjs",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
    "jest.config.ts",
    "jest.config.js",
    "vitest.config.ts",
    "vitest.config.js",
    "README.md",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
PATH_TOKEN_STOPWORDS = {
    "app",
    "apps",
    "src",
    "lib",
    "server",
    "client",
    "components",
    "component",
    "pages",
    "page",
    "routes",
    "route",
    "common",
    "feature",
    "features",
    "module",
    "modules",
    "latest",
    "main",
    "index",
    "utils",
    "hooks",
    "styles",
    "style",
    "desktop",
    "users",
    "boram",
    "tmp",
    "temp",
}
SUBJECT_TOKEN_STOPWORDS = {
    "add",
    "adjust",
    "build",
    "bump",
    "change",
    "cleanup",
    "create",
    "docs",
    "enable",
    "ensure",
    "feat",
    "feature",
    "fix",
    "guard",
    "harden",
    "improve",
    "make",
    "merge",
    "perf",
    "refactor",
    "remove",
    "rename",
    "revert",
    "stabilize",
    "support",
    "test",
    "tests",
    "update",
    "use",
}
KEYWORD_ALIASES = {
    "uploads": "upload",
    "uploaded": "upload",
    "uploading": "upload",
    "wizards": "wizard",
    "guidance": "guide",
    "guided": "guide",
    "contracts": "contract",
    "budgets": "budget",
    "previews": "preview",
    "timeseries": "timeseries",
    "retrospectives": "retrospective",
    "training": "training",
    "rlhf": "rlhf",
    "drive": "drive",
    "bff": "bff",
}
SHORT_TOKENS = {"ai", "ui", "ux", "qa", "rlhf", "bff", "ocr"}


def _local_now(now: datetime | None = None) -> datetime:
    base = now or datetime.now().astimezone()
    if base.tzinfo is None:
        return base.astimezone()
    return base.astimezone()


def _coerce_date(raw: str | date | datetime) -> date:
    if isinstance(raw, datetime):
        return raw.astimezone().date() if raw.tzinfo is not None else raw.date()
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw))


def _day_bounds(target_date: date, *, tz_ref: datetime | None = None) -> tuple[datetime, datetime]:
    ref = _local_now(tz_ref)
    start = datetime.combine(target_date, time.min, tzinfo=ref.tzinfo)
    end = start + timedelta(days=1)
    return start, end


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
                    "ts": local_ts.isoformat(),
                    "session_id": str(row.get("session_id", "")).strip(),
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


def _parse_log_records(raw: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    records: list[dict[str, Any]] = []
    for chunk in raw.split("\x1e"):
        piece = chunk.strip()
        if not piece:
            continue
        lines = [line.rstrip() for line in piece.splitlines() if line.strip()]
        if not lines:
            continue
        header = lines[0]
        parts = header.split("\x1f")
        if len(parts) < 4:
            continue
        commit_files = [line.strip() for line in lines[1:] if line.strip()]
        records.append(
            {
                "sha": parts[0].strip(),
                "short_sha": parts[1].strip(),
                "committed_at": parts[2].strip(),
                "subject": parts[3].strip(),
                "files": commit_files[:20],
            }
        )
    return records


def _normalize_repo_path(raw: str) -> str:
    return str(raw or "").replace("\\", "/").lstrip("./").strip()


def _classify_repo_path(raw: str) -> str:
    normalized = _normalize_repo_path(raw).lower()
    if not normalized:
        return "source_code"

    parts = [part for part in normalized.split("/") if part]
    filename = parts[-1] if parts else normalized
    suffix = Path(filename).suffix.lower()

    if any(part in {".git", "node_modules", ".venv"} for part in parts):
        return "ignored"
    if normalized.startswith("logs/") or suffix == ".log":
        return "ops_log"
    if any(part in {".next", "__pycache__", ".weekly-memo-cache", "dist", "build", "coverage"} for part in parts):
        return "generated_artifact"
    if suffix in {".jsonl", ".pyc"}:
        return "generated_artifact"
    if any(part in {"tests", "test", "__tests__", "__mocks__", "fixtures"} for part in parts):
        return "test"
    if ".test." in normalized or ".spec." in normalized or normalized.endswith("_test.py"):
        return "test"
    if normalized.startswith("docs/") or normalized.startswith(".github/") or normalized.startswith("schedules/"):
        return "docs_config"
    if filename in CONFIG_FILENAMES:
        return "docs_config"
    if suffix in {".md", ".mdx", ".toml", ".yaml", ".yml", ".ini", ".cfg"}:
        return "docs_config"
    return "source_code"


def _tokenize(raw: str, *, stopwords: set[str]) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", str(raw or "").lower().replace("-", " ").replace("_", " ")):
        alias = KEYWORD_ALIASES.get(token, token)
        if alias in stopwords:
            continue
        if alias.isdigit():
            continue
        if len(alias) < 3 and alias not in SHORT_TOKENS:
            continue
        tokens.append(alias)
    return tokens


def _subject_keywords(subjects: list[str], repo_name: str) -> list[str]:
    repo_tokens = set(_tokenize(repo_name, stopwords=set()))
    counter: Counter[str] = Counter()
    for subject in subjects:
        cleaned = re.sub(r"^[a-z]+(?:\([^)]+\))?!?:\s*", "", str(subject or "").lower()).strip()
        for token in _tokenize(cleaned, stopwords=SUBJECT_TOKEN_STOPWORDS):
            if token in repo_tokens:
                continue
            counter[token] += 3
    return [token for token, _ in counter.most_common(6)]


def _path_keywords(paths: list[str], repo_name: str) -> list[str]:
    repo_tokens = set(_tokenize(repo_name, stopwords=set()))
    counter: Counter[str] = Counter()
    for path in paths:
        normalized = _normalize_repo_path(path).lower()
        for token in _tokenize(normalized, stopwords=PATH_TOKEN_STOPWORDS):
            if token in repo_tokens:
                continue
            counter[token] += 1
    return [token for token, _ in counter.most_common(8)]


def _build_stream_focus(repo_name: str, subjects: list[str], paths: list[str]) -> str:
    focus_tokens: list[str] = []
    for token in _subject_keywords(subjects, repo_name) + _path_keywords(paths, repo_name):
        if token in focus_tokens:
            continue
        focus_tokens.append(token)
        if len(focus_tokens) >= 3:
            break
    if not focus_tokens:
        return "핵심 구현"
    return "/".join(focus_tokens)


def _stream_score(repo: dict[str, Any]) -> float:
    category_counts = repo.get("file_category_counts", {}) if isinstance(repo.get("file_category_counts", {}), dict) else {}
    delivery_commits = int(repo.get("delivery_commit_count", 0) or 0)
    return (
        delivery_commits * 8
        + int(category_counts.get("source_code", 0) or 0) * 2.5
        + int(category_counts.get("test", 0) or 0) * 1.5
        + int(category_counts.get("docs_config", 0) or 0) * 1.0
    )


def _collect_repo_activity(
    repo_root: Path,
    *,
    target_date: date,
    max_files: int = 20,
) -> dict[str, Any]:
    start, end = _day_bounds(target_date)
    branch = _run_git(["branch", "--show-current"], cwd=repo_root) or "-"
    log_raw = _run_git(
        [
            "log",
            f"--since={start.isoformat()}",
            f"--until={end.isoformat()}",
            "--pretty=format:%x1e%H%x1f%h%x1f%ad%x1f%s",
            "--date=iso",
            "--name-only",
            "--",
            ".",
        ],
        cwd=repo_root,
    )
    commits = _parse_log_records(log_raw)

    file_category_counts: Counter[str] = Counter()
    delivery_touched_files: list[dict[str, str]] = []
    generated_touched_files: list[dict[str, str]] = []
    ops_touched_files: list[dict[str, str]] = []
    docs_touched_files: list[dict[str, str]] = []
    test_touched_files: list[dict[str, str]] = []
    touched_files: list[dict[str, str]] = []

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.parts)
        if ".git" in parts or "node_modules" in parts or ".next" in parts or ".venv" in parts:
            continue
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        except OSError:
            continue
        if modified_at.date() != target_date:
            continue
        relative_path = str(path.relative_to(repo_root))
        category = _classify_repo_path(relative_path)
        if category == "ignored":
            continue
        item = {
            "path": relative_path,
            "modified_at": modified_at.isoformat(),
            "category": category,
        }
        file_category_counts[category] += 1
        touched_files.append(item)
        if category == "source_code":
            delivery_touched_files.append(item)
        elif category == "test":
            test_touched_files.append(item)
        elif category == "docs_config":
            docs_touched_files.append(item)
        elif category == "generated_artifact":
            generated_touched_files.append(item)
        elif category == "ops_log":
            ops_touched_files.append(item)

    touched_files.sort(key=lambda item: item["modified_at"])
    delivery_touched_files.sort(key=lambda item: item["modified_at"])
    test_touched_files.sort(key=lambda item: item["modified_at"])
    docs_touched_files.sort(key=lambda item: item["modified_at"])
    generated_touched_files.sort(key=lambda item: item["modified_at"])
    ops_touched_files.sort(key=lambda item: item["modified_at"])

    commit_file_counter: Counter[str] = Counter()
    delivery_commit_count = 0
    ops_only_commit_count = 0
    commit_category_counts: Counter[str] = Counter()
    commit_rows: list[dict[str, Any]] = []
    commit_subjects: list[str] = []

    for commit in commits:
        commit_counts: Counter[str] = Counter()
        delivery_files: list[str] = []
        for file_path in commit.get("files", []):
            normalized = _normalize_repo_path(file_path)
            category = _classify_repo_path(normalized)
            if category == "ignored":
                continue
            commit_counts[category] += 1
            commit_category_counts[category] += 1
            if category in DELIVERY_CATEGORIES:
                commit_file_counter[normalized] += 1
                delivery_files.append(normalized)
        commit_subjects.append(str(commit.get("subject", "")).strip())
        if sum(commit_counts.get(category, 0) for category in DELIVERY_CATEGORIES) > 0:
            delivery_commit_count += 1
        elif commit_counts.get("generated_artifact", 0) > 0 or commit_counts.get("ops_log", 0) > 0:
            ops_only_commit_count += 1
        commit_rows.append(
            {
                **commit,
                "file_category_counts": dict(commit_counts),
                "delivery_file_count": sum(commit_counts.get(category, 0) for category in DELIVERY_CATEGORIES),
                "delivery_files": delivery_files[:8],
            }
        )

    delivery_paths = [
        str(item.get("path", "")).strip()
        for item in [*delivery_touched_files, *test_touched_files, *docs_touched_files]
        if str(item.get("path", "")).strip()
    ]
    stream_focus = _build_stream_focus(repo_root.name, commit_subjects, delivery_paths)
    stream_score = _stream_score(
        {
            "delivery_commit_count": delivery_commit_count,
            "file_category_counts": dict(file_category_counts),
        }
    )

    return {
        "name": repo_root.name,
        "path": str(repo_root),
        "branch": branch.strip() or "-",
        "commit_count": len(commits),
        "delivery_commit_count": delivery_commit_count,
        "ops_only_commit_count": ops_only_commit_count,
        "commits": commit_rows,
        "touched_file_count": len(touched_files),
        "delivery_touched_file_count": len(delivery_touched_files) + len(test_touched_files) + len(docs_touched_files),
        "touched_files": touched_files[:max_files],
        "delivery_touched_files": [*delivery_touched_files[:8], *test_touched_files[:6], *docs_touched_files[:6]][:max_files],
        "generated_touched_files": generated_touched_files[:8],
        "ops_touched_files": ops_touched_files[:8],
        "file_category_counts": dict(file_category_counts),
        "commit_category_counts": dict(commit_category_counts),
        "top_commit_files": [
            {"path": file_path, "count": count}
            for file_path, count in commit_file_counter.most_common(8)
        ],
        "stream_focus": stream_focus,
        "stream_score": round(stream_score, 1),
    }


def _candidate_repo_roots(
    *,
    repo_roots: list[str],
    rollout_rows: list[dict[str, Any]],
    fallback_workdir: Path,
) -> list[Path]:
    candidates: list[Path] = []
    for item in repo_roots:
        text = str(item or "").strip()
        if not text:
            continue
        candidates.append(Path(text).expanduser().resolve())
    candidates.append(fallback_workdir.resolve())
    for row in rollout_rows:
        for item in row.get("top_workdirs", []) or []:
            if not isinstance(item, dict):
                continue
            workdir_value = str(item.get("workdir", "")).strip()
            if workdir_value:
                candidates.append(Path(workdir_value).expanduser().resolve())

    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        root = _repo_root(candidate)
        if root is None or root in seen:
            continue
        seen.add(root)
        resolved.append(root)
    return resolved


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 1)


def _build_primary_streams(repo_activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    streams: list[dict[str, Any]] = []
    for repo in repo_activity:
        score = float(repo.get("stream_score", 0.0) or 0.0)
        if score <= 0:
            continue
        stream = {
            "repo_name": str(repo.get("name", "")).strip() or "unknown",
            "focus": str(repo.get("stream_focus", "")).strip() or "핵심 구현",
            "score": score,
            "delivery_commit_count": int(repo.get("delivery_commit_count", 0) or 0),
            "delivery_touched_file_count": int(repo.get("delivery_touched_file_count", 0) or 0),
        }
        streams.append(stream)
    streams.sort(
        key=lambda item: (
            float(item.get("score", 0.0) or 0.0),
            int(item.get("delivery_commit_count", 0) or 0),
            str(item.get("repo_name", "")),
        ),
        reverse=True,
    )
    if len(streams) <= 1:
        return streams
    top, second = streams[0], streams[1]
    if float(top["score"]) >= float(second["score"]) * 1.6:
        return [top]
    return streams[:2]


def _build_coverage_note(history_prompt_count: int, rollout_prompt_count: int) -> str:
    if history_prompt_count <= 0 and rollout_prompt_count <= 0:
        return "history와 rollout prompt 근거가 모두 비어 있습니다."
    if history_prompt_count > 0 and rollout_prompt_count <= 0:
        return f"history 기준 {history_prompt_count}개가 있지만 rollout 캡처가 비어 있어 세션 추적이 부분적입니다."
    if history_prompt_count <= 0 and rollout_prompt_count > 0:
        return f"rollout 기준 {rollout_prompt_count}개만 남아 있어 사용자 프롬프트 원문 근거가 부족합니다."
    diff = abs(history_prompt_count - rollout_prompt_count)
    baseline = max(history_prompt_count, rollout_prompt_count, 1)
    if diff / baseline >= 0.25:
        return (
            f"history 기준 {history_prompt_count}개, rollout 기준 {rollout_prompt_count}개라 "
            "캡처 범위가 엇갈립니다."
        )
    return f"history {history_prompt_count}개와 rollout {rollout_prompt_count}개가 큰 차이 없이 맞습니다."


def _condense_prompt_text(text: str, *, limit: int = 260) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    counter = Counter(lines)
    condensed: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        repeat_count = counter[line]
        if repeat_count > 1:
            condensed.append(f"{line} (+{repeat_count - 1} similar lines)")
        else:
            condensed.append(line)
        if len(condensed) >= 4:
            break
    output = " / ".join(condensed)
    if len(output) > limit:
        return output[: limit - 1].rstrip() + "…"
    return output


def _compact_prompt_rows(prompt_rows: list[dict[str, Any]], *, limit: int = 14) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for row in prompt_rows:
        condensed = _condense_prompt_text(str(row.get("text", "")).strip())
        if not condensed:
            continue
        if compacted and compacted[-1]["text"] == condensed:
            compacted[-1]["repeat_count"] = int(compacted[-1].get("repeat_count", 1) or 1) + 1
            continue
        compacted.append(
            {
                "ts": str(row.get("ts", "")).strip(),
                "text": condensed,
                "repeat_count": 1,
            }
        )
        if len(compacted) >= limit:
            break
    return compacted


def _artifact_heavy_repos(repo_activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for repo in repo_activity:
        category_counts = repo.get("file_category_counts", {}) if isinstance(repo.get("file_category_counts", {}), dict) else {}
        delivery_files = int(repo.get("delivery_touched_file_count", 0) or 0)
        delivery_commits = int(repo.get("delivery_commit_count", 0) or 0)
        generated_files = int(category_counts.get("generated_artifact", 0) or 0)
        ops_files = int(category_counts.get("ops_log", 0) or 0)
        if generated_files + ops_files <= 0:
            continue
        if delivery_files <= 0 and delivery_commits <= 0:
            rows.append(repo)
            continue
        if delivery_commits <= 1 and generated_files + ops_files >= max(6, delivery_files * 3):
            rows.append(repo)
    rows.sort(
        key=lambda item: (
            int((item.get("file_category_counts", {}) or {}).get("generated_artifact", 0) or 0)
            + int((item.get("file_category_counts", {}) or {}).get("ops_log", 0) or 0),
            str(item.get("name", "")),
        ),
        reverse=True,
    )
    return rows


def collect_daily_retrospective_evidence(
    *,
    target_date: str | date | datetime,
    workdir: str | Path,
    history_file: str | Path | None = None,
    timeseries_file: str | Path | None = None,
    sessions_root: str | Path | None = None,
    repo_roots: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    target_day = _coerce_date(target_date)
    local_now = _local_now(now)
    workdir_path = Path(workdir).expanduser().resolve()
    history_path = Path(history_file or (Path.home() / ".codex" / "history.jsonl")).expanduser().resolve()

    prompt_rows = _load_prompt_rows(history_path, target_date=target_day)

    rollout_rows: list[dict[str, Any]] = []
    sessions_path = Path(sessions_root).expanduser().resolve() if sessions_root else None
    if sessions_path is not None and sessions_path.exists():
        rollout_rows = collect_codex_rollout_snapshots(
            start_date=target_day.isoformat(),
            end_date=target_day.isoformat(),
            sessions_root=sessions_path,
        )
    elif timeseries_file:
        timeseries_path = Path(timeseries_file).expanduser().resolve()
        if timeseries_path.exists():
            rollout_rows = load_timeseries_rows(
                timeseries_path,
                start_date=target_day.isoformat(),
                end_date=target_day.isoformat(),
                kinds=["codex_rollout"],
            )

    repo_activity = [
        _collect_repo_activity(repo_root, target_date=target_day)
        for repo_root in _candidate_repo_roots(
            repo_roots=list(repo_roots or []),
            rollout_rows=rollout_rows,
            fallback_workdir=workdir_path,
        )
    ]
    repo_activity = [
        repo
        for repo in repo_activity
        if int(repo.get("commit_count", 0) or 0) > 0 or int(repo.get("touched_file_count", 0) or 0) > 0
    ]
    repo_activity.sort(
        key=lambda item: (
            float(item.get("stream_score", 0.0) or 0.0),
            int(item.get("delivery_commit_count", 0) or 0),
            int(item.get("touched_file_count", 0) or 0),
            str(item.get("name", "")),
        ),
        reverse=True,
    )

    prompt_lengths = [len(str(item.get("text", ""))) for item in prompt_rows]
    session_counter: Counter[str] = Counter()
    for row in prompt_rows:
        session_id = str(row.get("session_id", "")).strip()
        if session_id:
            session_counter[session_id] += 1
    feedback_summary = summarize_turn_feedback(prompt_rows)

    rollout_summary = summarize_period(rollout_rows) if rollout_rows else {
        "session_count": 0,
        "total_user_prompts": 0,
        "total_exec_commands": 0,
        "total_duration_minutes": 0.0,
        "total_feedback_prompts": 0,
        "feedback_totals": {"accepted": 0, "corrected": 0, "retried": 0, "ambiguous": 0},
        "feedback_rates": {"accepted": 0.0, "corrected": 0.0, "retried": 0.0, "ambiguous": 0.0},
        "top_correction_hints": [],
        "top_command_heads": [],
        "top_workdirs": [],
        "theme_totals": {},
        "daily": [],
    }

    history_prompt_count = len(prompt_rows)
    rollout_prompt_count = int(rollout_summary.get("total_user_prompts", 0) or 0)
    primary_streams = _build_primary_streams(repo_activity)
    coverage_note = _build_coverage_note(history_prompt_count, rollout_prompt_count)

    return {
        "date": target_day.isoformat(),
        "generated_at": local_now.isoformat(),
        "history_file": str(history_path),
        "prompt_count": history_prompt_count,
        "history_prompt_count": history_prompt_count,
        "rollout_prompt_count": rollout_prompt_count,
        "coverage_note": coverage_note,
        "prompt_rows": prompt_rows,
        "prompt_rows_compact": _compact_prompt_rows(prompt_rows),
        "prompt_session_breakdown": [
            {"session_id": session_id, "count": count}
            for session_id, count in session_counter.most_common(10)
        ],
        "prompt_chars_avg": _safe_ratio(sum(prompt_lengths), len(prompt_lengths)) if prompt_lengths else 0.0,
        "feedback_prompt_count": int(feedback_summary.get("feedback_prompt_count", 0) or 0),
        "feedback_counts": feedback_summary.get("feedback_counts", {}),
        "feedback_rates": feedback_summary.get("feedback_rates", {}),
        "top_correction_hints": feedback_summary.get("top_correction_hints", []),
        "recent_feedback": feedback_summary.get("recent_feedback", []),
        "rollout_rows": rollout_rows,
        "rollout_summary": rollout_summary,
        "repo_activity": repo_activity,
        "repo_names": [str(repo.get("name", "")) for repo in repo_activity if str(repo.get("name", "")).strip()],
        "primary_streams": primary_streams,
    }


def _section(title: str, lines: list[str]) -> list[str]:
    output = [f"## {title}"]
    output.extend(lines if lines else ["- 근거가 부족합니다."])
    output.append("")
    return output


def _headline_from_streams(target_date: str, primary_streams: list[dict[str, Any]], artifact_repos: list[dict[str, Any]]) -> str:
    if not primary_streams:
        if artifact_repos:
            names = ", ".join(f"`{repo.get('name', '-')}`" for repo in artifact_repos[:2])
            return f"- {target_date}은 {names} 쪽 운영 산출물 갱신 비중이 커서 중심 delivery stream을 특정하기 어려웠습니다."
        return f"- {target_date}은 프롬프트와 Git 근거가 얕아 중심 delivery stream을 특정하기 어려웠습니다."

    if len(primary_streams) == 1:
        stream = primary_streams[0]
        line = (
            f"- {target_date}의 중심 delivery stream은 "
            f"`{stream.get('repo_name', '-')}`의 {stream.get('focus', '핵심 구현')} 흐름이었습니다."
        )
    else:
        first, second = primary_streams[:2]
        line = (
            f"- {target_date}은 `{first.get('repo_name', '-')}`의 {first.get('focus', '핵심 구현')} 작업과 "
            f"`{second.get('repo_name', '-')}`의 {second.get('focus', '핵심 구현')} 작업이 함께 강했던 날이었습니다."
        )
    if artifact_repos:
        names = ", ".join(f"`{repo.get('name', '-')}`" for repo in artifact_repos[:2])
        line += f" 다만 {names}의 활동은 구현보다 운영 산출물 비중이 더 높았습니다."
    return line


def _build_judgement_lines(evidence: dict[str, Any]) -> list[str]:
    target_date = str(evidence.get("date", "")).strip()
    rollout_summary = evidence.get("rollout_summary", {}) if isinstance(evidence.get("rollout_summary", {}), dict) else {}
    repo_activity = [repo for repo in evidence.get("repo_activity", []) if isinstance(repo, dict)]
    primary_streams = [stream for stream in evidence.get("primary_streams", []) if isinstance(stream, dict)]
    artifact_repos = _artifact_heavy_repos(repo_activity)
    feedback_counts = evidence.get("feedback_counts", {}) if isinstance(evidence.get("feedback_counts", {}), dict) else {}

    total_exec = int(rollout_summary.get("total_exec_commands", 0) or 0)
    delivery_commit_total = sum(int(repo.get("delivery_commit_count", 0) or 0) for repo in repo_activity)
    delivery_file_total = sum(int(repo.get("delivery_touched_file_count", 0) or 0) for repo in repo_activity)
    corrected = int(feedback_counts.get("corrected", 0) or 0)
    retried = int(feedback_counts.get("retried", 0) or 0)
    accepted = int(feedback_counts.get("accepted", 0) or 0)

    return [
        _headline_from_streams(target_date, primary_streams, artifact_repos),
        (
            f"- delivery 근거는 commits {delivery_commit_total}건, source/test/config 파일 {delivery_file_total}건이며, "
            f"rollout exec은 {total_exec}회였습니다."
        ),
        f"- 프롬프트 coverage는 {str(evidence.get('coverage_note', '')).strip() or '근거 부족'}",
        (
            f"- next-state feedback은 corrected {corrected}, retried {retried}, accepted {accepted}로 "
            "반복 교정 압력을 보여줍니다."
        ),
    ]


def _build_interpretation_lines(evidence: dict[str, Any]) -> list[str]:
    repo_activity = [repo for repo in evidence.get("repo_activity", []) if isinstance(repo, dict)]
    primary_streams = [stream for stream in evidence.get("primary_streams", []) if isinstance(stream, dict)]
    lines: list[str] = []
    for stream in primary_streams:
        lines.append(
            f"- `{stream.get('repo_name', '-')}`는 delivery commits {int(stream.get('delivery_commit_count', 0) or 0)}건, "
            f"delivery files {int(stream.get('delivery_touched_file_count', 0) or 0)}건으로 상위 stream으로 분류됐고, "
            f"focus는 {stream.get('focus', '핵심 구현')}으로 읽혔습니다."
        )

    for repo in _artifact_heavy_repos(repo_activity)[:2]:
        category_counts = repo.get("file_category_counts", {}) if isinstance(repo.get("file_category_counts", {}), dict) else {}
        lines.append(
            f"- `{repo.get('name', '-')}`는 source/test/config {int(repo.get('delivery_touched_file_count', 0) or 0)}건보다 "
            f"generated {int(category_counts.get('generated_artifact', 0) or 0)}건, "
            f"ops/log {int(category_counts.get('ops_log', 0) or 0)}건이 많아 운영 activity로 분리해서 해석했습니다."
        )

    if str(evidence.get("coverage_note", "")).strip():
        lines.append(f"- 회고 coverage 판단은 {str(evidence.get('coverage_note', '')).strip()}")
    return lines


def _build_risk_lines(evidence: dict[str, Any]) -> list[str]:
    repo_activity = [repo for repo in evidence.get("repo_activity", []) if isinstance(repo, dict)]
    feedback_counts = evidence.get("feedback_counts", {}) if isinstance(evidence.get("feedback_counts", {}), dict) else {}
    corrected = int(feedback_counts.get("corrected", 0) or 0)
    retried = int(feedback_counts.get("retried", 0) or 0)
    accepted = int(feedback_counts.get("accepted", 0) or 0)
    primary_streams = [stream for stream in evidence.get("primary_streams", []) if isinstance(stream, dict)]
    delivery_repos = [repo for repo in repo_activity if float(repo.get("stream_score", 0.0) or 0.0) > 0]
    lines: list[str] = []

    coverage_note = str(evidence.get("coverage_note", "")).strip()
    if "엇갈립니다" in coverage_note or "비어" in coverage_note or "부분적" in coverage_note:
        lines.append(f"- prompt coverage가 불완전해 narrative가 일부 세션을 놓칠 위험이 있습니다. {coverage_note}")
    if corrected + retried > max(accepted * 2, 4):
        lines.append(
            "- corrected/retried가 accepted보다 훨씬 많아, 설명 방식이나 범위 정렬이 자주 다시 요구되고 있습니다."
        )
    if len(delivery_repos) > max(2, len(primary_streams)):
        lines.append(
            f"- delivery score가 의미 있게 나온 레포가 {len(delivery_repos)}개라 context switching 비용이 커질 수 있습니다."
        )
    artifact_repos = _artifact_heavy_repos(repo_activity)
    if artifact_repos:
        names = ", ".join(f"`{repo.get('name', '-')}`" for repo in artifact_repos[:2])
        lines.append(f"- {names}의 generated/ops 흔적이 많아 구현 신호가 다시 자동 산출물에 묻힐 수 있습니다.")
    if not lines:
        lines.append("- 현재 근거에서는 큰 구조적 리스크보다 상위 delivery stream 집중 유지가 더 중요해 보였습니다.")
    return lines


def _build_next_actions(evidence: dict[str, Any]) -> list[str]:
    primary_streams = [stream for stream in evidence.get("primary_streams", []) if isinstance(stream, dict)]
    lines: list[str] = []
    next_index = 1
    for stream in primary_streams[:2]:
        lines.append(
            f"{next_index}. `{stream.get('repo_name', '-')}`의 {stream.get('focus', '핵심 구현')} 흐름을 "
            "한 개 happy path와 테스트 기준으로 닫습니다."
        )
        next_index += 1

    coverage_note = str(evidence.get("coverage_note", "")).strip()
    if "엇갈립니다" in coverage_note or "비어" in coverage_note or "부분적" in coverage_note:
        lines.append(f"{next_index}. history prompt와 rollout prompt 집계를 reconcile해서 회고 coverage를 맞춥니다.")
        next_index += 1

    artifact_repos = _artifact_heavy_repos([repo for repo in evidence.get("repo_activity", []) if isinstance(repo, dict)])
    if artifact_repos:
        names = ", ".join(f"`{repo.get('name', '-')}`" for repo in artifact_repos[:2])
        lines.append(f"{next_index}. {names}의 generated artifact와 ops 로그는 delivery 집계와 포스트 서사에서 계속 분리합니다.")
        next_index += 1

    if next_index <= 3:
        lines.append(f"{next_index}. feedback 상위 교정 힌트를 다음 세션 시작 brief에 반영해 재수정 비용을 줄입니다.")
    return lines


def build_daily_retrospective_markdown(evidence: dict[str, Any]) -> str:
    target_date = str(evidence.get("date", "")).strip()
    rollout_summary = evidence.get("rollout_summary", {}) if isinstance(evidence.get("rollout_summary", {}), dict) else {}
    repo_activity = [repo for repo in evidence.get("repo_activity", []) if isinstance(repo, dict)]
    prompt_rows = [row for row in evidence.get("prompt_rows_compact", []) if isinstance(row, dict)]

    total_sessions = int(rollout_summary.get("session_count", 0) or 0)
    rollout_prompt_count = int(evidence.get("rollout_prompt_count", 0) or 0)
    history_prompt_count = int(evidence.get("history_prompt_count", 0) or 0)
    total_exec = int(rollout_summary.get("total_exec_commands", 0) or 0)
    total_duration = float(rollout_summary.get("total_duration_minutes", 0.0) or 0.0)
    theme_totals = rollout_summary.get("theme_totals", {}) if isinstance(rollout_summary.get("theme_totals", {}), dict) else {}
    top_commands = [item for item in rollout_summary.get("top_command_heads", []) if isinstance(item, dict)]
    top_workdirs = [item for item in rollout_summary.get("top_workdirs", []) if isinstance(item, dict)]
    feedback_counts = evidence.get("feedback_counts", {}) if isinstance(evidence.get("feedback_counts", {}), dict) else {}
    top_correction_hints = [item for item in evidence.get("top_correction_hints", []) if isinstance(item, dict)]
    recent_feedback = [item for item in evidence.get("recent_feedback", []) if isinstance(item, dict)]

    commit_total = sum(int(repo.get("commit_count", 0) or 0) for repo in repo_activity)
    touched_total = sum(int(repo.get("touched_file_count", 0) or 0) for repo in repo_activity)
    delivery_commit_total = sum(int(repo.get("delivery_commit_count", 0) or 0) for repo in repo_activity)
    delivery_touched_total = sum(int(repo.get("delivery_touched_file_count", 0) or 0) for repo in repo_activity)

    repo_headline = ", ".join(
        f"{repo.get('name', '-')}"
        + (
            f"(delivery {int(repo.get('delivery_commit_count', 0) or 0)} commits)"
            if int(repo.get("delivery_commit_count", 0) or 0) > 0
            else f"(ops/generated {int((repo.get('file_category_counts', {}) or {}).get('ops_log', 0) or 0) + int((repo.get('file_category_counts', {}) or {}).get('generated_artifact', 0) or 0)} files)"
        )
        for repo in repo_activity[:4]
    ) or "근거 부족"

    lines: list[str] = [
        f"# Daily Retrospective — {target_date}",
        "",
        f"- Generated at: {str(evidence.get('generated_at', '')).strip() or '-'}",
        (
            f"- Rollout capture: sessions {total_sessions}, rollout prompts {rollout_prompt_count}, "
            f"exec commands {total_exec}, tracked minutes {round(total_duration, 1)}"
        ),
        (
            f"- History capture: prompts {history_prompt_count}, prompt avg length "
            f"{float(evidence.get('prompt_chars_avg', 0.0) or 0.0)} chars"
        ),
        f"- Active repos: {repo_headline}",
        "",
    ]

    lines.extend(_section("한 줄 판단", _build_judgement_lines(evidence)))

    signal_lines = [
        f"- Coverage: {str(evidence.get('coverage_note', '')).strip() or '근거 부족'}",
        f"- History prompt 수: {history_prompt_count}",
        f"- Rollout prompt 수: {rollout_prompt_count}",
        (
            "- Codex rollout 기준 workdir 상위: "
            + (", ".join(f"{item.get('workdir')} ({item.get('count')})" for item in top_workdirs[:5]) or "근거 부족")
        ),
        (
            "- 테마 신호: "
            + (", ".join(f"{theme} {count}" for theme, count in sorted(theme_totals.items(), key=lambda item: item[1], reverse=True)[:6]) or "근거 부족")
        ),
        (
            f"- delivery commits {delivery_commit_total}건 / delivery files {delivery_touched_total}건 / "
            f"전체 touched files {touched_total}건 / 전체 commits {commit_total}건"
        ),
        (
            f"- follow-up prompt 수: {int(evidence.get('feedback_prompt_count', 0) or 0)} "
            f"(corrected {int(feedback_counts.get('corrected', 0) or 0)}, "
            f"retried {int(feedback_counts.get('retried', 0) or 0)}, "
            f"accepted {int(feedback_counts.get('accepted', 0) or 0)})"
        ),
        (
            "- 상위 명령: "
            + (", ".join(f"{item.get('command')} {item.get('count')}" for item in top_commands[:5]) or "근거 부족")
        ),
    ]
    lines.extend(_section("정량 신호", signal_lines))

    prompt_lines: list[str] = []
    for row in prompt_rows[:14]:
        suffix = ""
        if int(row.get("repeat_count", 1) or 1) > 1:
            suffix = f" (x{int(row.get('repeat_count', 1) or 1)})"
        prompt_lines.append(f"- {str(row.get('ts', '')).split('T')[-1][:8]} · {str(row.get('text', '')).strip()}{suffix}")
    lines.extend(_section("프롬프트 흐름", prompt_lines))

    feedback_lines: list[str] = []
    for item in top_correction_hints[:6]:
        label = str(item.get("label", "")).strip()
        count = int(item.get("count", 0) or 0)
        examples = [str(example).strip() for example in item.get("examples", []) or [] if str(example).strip()]
        if not label or count <= 0:
            continue
        feedback_lines.append(f"- {label}: {count}회")
        if examples:
            feedback_lines.append(f"  - 예시: {_condense_prompt_text(examples[0], limit=180)}")
    if recent_feedback:
        latest = recent_feedback[-1]
        feedback_lines.append(
            f"- 가장 최근 반응: {str(latest.get('outcome', 'ambiguous')).strip()} · "
            f"{_condense_prompt_text(str(latest.get('text', '')).strip(), limit=180)}"
        )
    lines.extend(_section("사용자 피드백 / 교정 신호", feedback_lines))

    repo_lines: list[str] = []
    for repo in repo_activity[:6]:
        name = str(repo.get("name", "-"))
        branch = str(repo.get("branch", "-"))
        category_counts = repo.get("file_category_counts", {}) if isinstance(repo.get("file_category_counts", {}), dict) else {}
        repo_lines.append(
            f"- `{name}` ({branch}): delivery commits {int(repo.get('delivery_commit_count', 0) or 0)}, "
            f"delivery files {int(repo.get('delivery_touched_file_count', 0) or 0)}, "
            f"generated {int(category_counts.get('generated_artifact', 0) or 0)}, "
            f"ops/log {int(category_counts.get('ops_log', 0) or 0)}"
        )
        commits = [commit for commit in repo.get("commits", []) if isinstance(commit, dict)]
        delivery_commits = [commit for commit in commits if int(commit.get("delivery_file_count", 0) or 0) > 0]
        for commit in delivery_commits[:6]:
            repo_lines.append(
                f"  - {str(commit.get('short_sha', '')).strip()} {str(commit.get('subject', '')).strip()}"
            )
        delivery_files = [item for item in repo.get("delivery_touched_files", []) if isinstance(item, dict)]
        if delivery_files:
            repo_lines.append(
                "  - delivery touched: "
                + ", ".join(str(item.get("path", "")).strip() for item in delivery_files[:8] if str(item.get("path", "")).strip())
            )
        elif repo.get("generated_touched_files") or repo.get("ops_touched_files"):
            non_delivery = [
                str(item.get("path", "")).strip()
                for item in [*(repo.get("generated_touched_files", []) or []), *(repo.get("ops_touched_files", []) or [])]
                if isinstance(item, dict) and str(item.get("path", "")).strip()
            ]
            if non_delivery:
                repo_lines.append("  - ops/generated only: " + ", ".join(non_delivery[:8]))
    lines.extend(_section("레포별 실제 구현 흔적", repo_lines))

    lines.extend(_section("해석", _build_interpretation_lines(evidence)))
    lines.extend(_section("리스크와 미완료", _build_risk_lines(evidence)))
    lines.extend(_section("다음 액션", _build_next_actions(evidence)))

    return "\n".join(lines).strip() + "\n"


def build_retrospective_post(
    *,
    evidence: dict[str, Any],
    markdown: str,
    source: str = "daily_retrospective_post",
    slot_ts: datetime | None = None,
) -> dict[str, Any]:
    target_date = str(evidence.get("date", "")).strip()
    rollout_summary = evidence.get("rollout_summary", {}) if isinstance(evidence.get("rollout_summary", {}), dict) else {}
    repo_activity = [repo for repo in evidence.get("repo_activity", []) if isinstance(repo, dict)]
    summary_line = ""
    for line in markdown.splitlines():
        if line.startswith("- ") and ("delivery stream" in line or "중심" in line):
            summary_line = line[2:].strip()
            break
    if not summary_line:
        summary_line = f"{target_date} retrospective"
    slot_local = slot_ts.astimezone() if slot_ts is not None else None
    title = f"Daily Retrospective — {target_date}"
    post_id = f"daily_retrospective:{target_date}"
    slug = target_date
    if slot_local is not None:
        slot_key = slot_local.strftime("%Y-%m-%dT%H")
        slot_label = slot_local.strftime("%Y-%m-%d %H:00")
        title = f"Retrospective Update — {slot_label}"
        post_id = f"daily_retrospective:{slot_key}"
        slug = slot_key

    commit_total = sum(int(repo.get("commit_count", 0) or 0) for repo in repo_activity)
    touched_file_total = sum(int(repo.get("touched_file_count", 0) or 0) for repo in repo_activity)
    delivery_commit_total = sum(int(repo.get("delivery_commit_count", 0) or 0) for repo in repo_activity)
    delivery_touched_total = sum(int(repo.get("delivery_touched_file_count", 0) or 0) for repo in repo_activity)
    generated_file_total = sum(
        int((repo.get("file_category_counts", {}) or {}).get("generated_artifact", 0) or 0) for repo in repo_activity
    )
    ops_file_total = sum(
        int((repo.get("file_category_counts", {}) or {}).get("ops_log", 0) or 0) for repo in repo_activity
    )
    return {
        "post_id": post_id,
        "slug": slug,
        "title": title,
        "date": target_date,
        "ts": slot_local.isoformat() if slot_local is not None else str(evidence.get("generated_at", "")).strip(),
        "summary": summary_line,
        "markdown": markdown,
        "repo_names": list(evidence.get("repo_names", []))[:8],
        "primary_streams": list(evidence.get("primary_streams", []))[:4],
        "prompt_count": int(evidence.get("prompt_count", 0) or 0),
        "history_prompt_count": int(evidence.get("history_prompt_count", 0) or 0),
        "rollout_prompt_count": int(evidence.get("rollout_prompt_count", 0) or 0),
        "coverage_note": str(evidence.get("coverage_note", "")).strip(),
        "feedback_prompt_count": int(evidence.get("feedback_prompt_count", 0) or 0),
        "feedback_counts": evidence.get("feedback_counts", {}),
        "top_correction_hints": evidence.get("top_correction_hints", []),
        "session_count": int(rollout_summary.get("session_count", 0) or 0),
        "exec_command_count": int(rollout_summary.get("total_exec_commands", 0) or 0),
        "duration_minutes": float(rollout_summary.get("total_duration_minutes", 0.0) or 0.0),
        "commit_count": commit_total,
        "delivery_commit_count": delivery_commit_total,
        "touched_file_count": touched_file_total,
        "delivery_file_count": delivery_touched_total,
        "generated_file_count": generated_file_total,
        "ops_file_count": ops_file_total,
        "top_command_heads": rollout_summary.get("top_command_heads", []),
        "top_workdirs": rollout_summary.get("top_workdirs", []),
        "theme_totals": rollout_summary.get("theme_totals", {}),
        "auto_posted": True,
        "source": source,
        "kind": "daily_retrospective",
    }


def append_retrospective_posts(path: str | Path, posts: list[dict[str, Any]]) -> int:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    if target.exists():
        with target.open("r", encoding="utf-8", errors="replace") as handle:
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
                post_id = str(row.get("post_id", "")).strip()
                if post_id:
                    existing[post_id] = row

    inserted = 0
    for post in posts:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("post_id", "")).strip()
        if not post_id:
            continue
        if post_id not in existing:
            inserted += 1
        existing[post_id] = post

    ordered = sorted(
        existing.values(),
        key=lambda item: (str(item.get("date", "")), str(item.get("post_id", ""))),
    )
    with target.open("w", encoding="utf-8") as handle:
        for post in ordered:
            handle.write(json.dumps(post, ensure_ascii=False) + "\n")
    return inserted


def write_retrospective_markdown(path: str | Path, markdown: str) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target
