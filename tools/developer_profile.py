from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from git_daily_summary import run as git_summary_run

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "developer_profile",
    "description": "shell 명령어와 git 이력을 분석하여 기술 스택, 역할, 스킬 성장 추이를 프로파일링합니다.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "days_back": {"type": "integer", "default": 30},
            "scan_all_repos": {"type": "boolean", "default": False},
        },
        "required": [],
    },
}

_ZSH_EXTENDED_RE = re.compile(r"^:\s*(\d+):\d+;(.+)$")


def _extract_base_command(cmd: str) -> str:
    command = (cmd or "").strip()
    command = command.split("|")[0].strip()
    if command.startswith("sudo "):
        command = command[5:].strip()
    parts = command.split()
    return parts[0] if parts else ""


def _load_shell_entries(days_back: int, history_file: str = "~/.zsh_history") -> list[dict[str, Any]]:
    path = Path(history_file).expanduser()
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    since_ts = (datetime.now() - timedelta(days=days_back)).timestamp()
    entries: list[dict[str, Any]] = []
    has_extended = False
    lines = text.splitlines()

    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        match = _ZSH_EXTENDED_RE.match(raw)
        if match:
            has_extended = True
            ts = float(match.group(1))
            if ts < since_ts:
                continue
            command = match.group(2).strip()
            entries.append({"timestamp": ts, "command": command})
        elif has_extended and entries:
            entries[-1]["command"] += "\n" + raw

    if not has_extended:
        now_ts = datetime.now().timestamp()
        for line in lines:
            raw = line.strip()
            if raw:
                entries.append({"timestamp": now_ts, "command": raw})

    return entries


def _discover_git_repos(scan_all_repos: bool) -> list[Path]:
    if not scan_all_repos:
        return [Path(".").resolve()]

    home = Path.home()
    cache_file = home / ".boramclaw_repos_cache"
    repos: list[Path] = []
    try:
        result = subprocess.run(
            ["find", str(home), "-maxdepth", "3", "-name", ".git", "-type", "d"],
            capture_output=True,
            text=True,
            timeout=15,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            repos = [Path(line).parent.resolve() for line in result.stdout.splitlines() if line.strip()]
            if repos:
                cache_file.write_text("\n".join(str(p) for p in repos), encoding="utf-8")
    except Exception:
        if cache_file.exists():
            repos = [Path(line).resolve() for line in cache_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return repos or [Path(".").resolve()]


def _collect_git_data(days_back: int, scan_all_repos: bool, context: dict[str, Any]) -> dict[str, Any]:
    repo_paths = _discover_git_repos(scan_all_repos)
    commits: list[dict[str, Any]] = []
    changed_files: list[str] = []
    for repo in repo_paths:
        result = git_summary_run({"repo_path": str(repo), "days": days_back}, context)
        if not result.get("ok"):
            continue
        for commit in result.get("commits", []):
            commit_row = dict(commit)
            commit_row["repo"] = repo.name
            commits.append(commit_row)
            files = commit.get("files", [])
            if isinstance(files, list):
                for item in files:
                    if isinstance(item, dict):
                        file_path = str(item.get("file", "")).strip()
                        if file_path:
                            changed_files.append(file_path)
                    elif isinstance(item, str):
                        changed_files.append(item)
    return {
        "repo_count": len(repo_paths),
        "commits": commits,
        "changed_files": changed_files,
    }


def _language_for_file(path: str) -> str | None:
    lower = path.lower()
    if lower.endswith(".py"):
        return "Python"
    if lower.endswith(".ts") or lower.endswith(".tsx"):
        return "TypeScript"
    if lower.endswith(".js") or lower.endswith(".jsx"):
        return "JavaScript/Node.js"
    if lower.endswith(".rs"):
        return "Rust"
    if lower.endswith(".go"):
        return "Go"
    if lower.endswith(".java"):
        return "Java"
    return None


def _command_language_tags(base_cmd: str, full_cmd: str) -> set[str]:
    lower_full = full_cmd.lower()
    tags: set[str] = set()
    if base_cmd in {"python", "python3", "pytest", "pip"}:
        tags.add("Python")
    if base_cmd in {"node", "npm", "npx", "yarn"}:
        tags.add("JavaScript/Node.js")
    if base_cmd in {"ts-node", "tsc"}:
        tags.add("TypeScript")
    if base_cmd in {"cargo", "rustc"}:
        tags.add("Rust")
    if base_cmd == "go" or lower_full.startswith("go run") or lower_full.startswith("go build"):
        tags.add("Go")
    if base_cmd in {"java", "mvn", "gradle"}:
        tags.add("Java")
    if base_cmd in {"docker", "docker-compose"}:
        tags.add("Docker")
    if base_cmd in {"kubectl", "helm"}:
        tags.add("Kubernetes")
    if base_cmd in {"git", "gh"}:
        tags.add("Version Control")
    return tags


def _language_expertise_level(unique_count: int) -> str:
    if unique_count >= 20:
        return "expert"
    if unique_count >= 5:
        return "intermediate"
    return "beginner"


def _infer_role_hint(language_breakdown: dict[str, float], command_counts: Counter[str], full_commands: list[str]) -> str:
    backend = language_breakdown.get("Python", 0.0) + language_breakdown.get("Java", 0.0) + language_breakdown.get("Go", 0.0)
    frontend = language_breakdown.get("JavaScript/Node.js", 0.0) + language_breakdown.get("TypeScript", 0.0)

    lower_commands = [cmd.lower() for cmd in full_commands]
    data_signals = sum(1 for cmd in lower_commands if any(token in cmd for token in ("jupyter", "pandas", "numpy", "sklearn")))
    devops_signals = command_counts.get("docker", 0) + command_counts.get("kubectl", 0) + command_counts.get("helm", 0)

    if devops_signals >= 15:
        return "devops"
    if data_signals >= 10:
        return "data"
    if backend >= 0.35 and frontend >= 0.35:
        return "fullstack"
    if backend > 0.5:
        return "backend"
    if frontend > 0.5:
        return "frontend"
    return "unknown"


def _normalize_breakdown(counts: dict[str, float]) -> dict[str, float]:
    total = sum(v for v in counts.values() if v > 0)
    if total <= 0:
        return {}
    return {k: round(v / total, 4) for k, v in counts.items() if v > 0}


def _detect_tech_stack(shell_data: dict, git_data: dict) -> dict:
    command_counts: Counter[str] = shell_data.get("command_counts", Counter())
    full_commands: list[str] = shell_data.get("full_commands", [])
    changed_files: list[str] = git_data.get("changed_files", [])

    combined_counts: dict[str, float] = {
        "Python": 0.0,
        "JavaScript/Node.js": 0.0,
        "TypeScript": 0.0,
        "Rust": 0.0,
        "Go": 0.0,
        "Java": 0.0,
        "Shell": 0.0,
    }

    language_command_sets: dict[str, set[str]] = {
        "Python": set(),
        "JavaScript/Node.js": set(),
        "TypeScript": set(),
        "Rust": set(),
        "Go": set(),
        "Java": set(),
    }

    framework_candidates: list[str] = []
    for full_cmd in full_commands:
        base = _extract_base_command(full_cmd)
        if not base:
            continue
        tags = _command_language_tags(base, full_cmd)
        if not tags:
            combined_counts["Shell"] += 1
            continue
        for tag in tags:
            if tag in combined_counts:
                combined_counts[tag] += 1
            if tag in language_command_sets:
                language_command_sets[tag].add(full_cmd.strip())
        if base in {"pytest", "docker", "docker-compose", "kubectl", "helm", "npm", "yarn"}:
            framework_candidates.append(base)

    for file_path in changed_files:
        language = _language_for_file(file_path)
        if language:
            combined_counts[language] += 1

    language_breakdown = _normalize_breakdown(combined_counts)
    primary_candidates = {k: v for k, v in language_breakdown.items() if k != "Shell"}
    primary_language = max(primary_candidates, key=primary_candidates.get) if primary_candidates else "Unknown"

    expertise_level = {}
    for language, commands in language_command_sets.items():
        if commands:
            expertise_level[language] = _language_expertise_level(len(commands))

    frameworks = sorted(set(framework_candidates))
    role_hint = _infer_role_hint(language_breakdown, command_counts, full_commands)

    return {
        "primary_language": primary_language,
        "language_breakdown": language_breakdown,
        "frameworks": frameworks,
        "role_hint": role_hint,
        "expertise_level": expertise_level,
    }


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _generate_role_insights(profile: dict, workday_data: dict) -> list[dict]:
    role = profile.get("role_hint", "unknown")
    changed_files: list[str] = workday_data.get("changed_files", [])
    base_counts: Counter[str] = workday_data.get("command_counts", Counter())
    full_commands: list[str] = workday_data.get("full_commands", [])

    insights: list[dict] = []
    total_files = max(1, len(changed_files))
    lower_files = [path.lower() for path in changed_files]
    lower_commands = [cmd.lower() for cmd in full_commands]

    if role == "backend":
        api_count = sum(1 for path in lower_files if any(token in path for token in ("api", "route", "handler", "controller")))
        test_runs = base_counts.get("pytest", 0) + base_counts.get("unittest", 0)
        python_runs = base_counts.get("python", 0) + base_counts.get("python3", 0) + test_runs
        db_count = sum(1 for path in lower_files if any(token in path for token in ("migration", "model", "schema", "query")))
        insights.extend(
            [
                {
                    "category": "api_focus",
                    "title": "API 엔드포인트 작업 비중",
                    "value": f"{_pct(api_count, total_files)}%",
                    "context": "라우팅/핸들러 관련 파일 비중입니다. 핵심 도메인 API 우선순위를 점검하세요.",
                },
                {
                    "category": "test_signal",
                    "title": "테스트 커버리지 신호",
                    "value": f"{_pct(test_runs, max(1, python_runs))}%",
                    "context": "Python 실행 대비 테스트 실행 비중입니다. 30% 이상이면 안정적입니다.",
                },
                {
                    "category": "db_work",
                    "title": "DB 관련 작업 비중",
                    "value": f"{_pct(db_count, total_files)}%",
                    "context": "모델/스키마 변경 비율입니다. 스키마 변경 시 마이그레이션 검증을 권장합니다.",
                },
            ]
        )
    elif role == "frontend":
        component_count = sum(1 for path in lower_files if path.endswith(".tsx") or path.endswith(".jsx"))
        style_count = sum(1 for path in lower_files if path.endswith(".css") or path.endswith(".scss"))
        build_runs = sum(1 for cmd in lower_commands if ("npm run build" in cmd or "yarn build" in cmd))
        rework_ratio = _pct(total_files - len(set(changed_files)), total_files)
        insights.extend(
            [
                {
                    "category": "component_changes",
                    "title": "컴포넌트 변경 빈도",
                    "value": f"{component_count}건",
                    "context": "주요 UI 컴포넌트 변경 건수입니다. 공통 컴포넌트 회귀 테스트를 권장합니다.",
                },
                {
                    "category": "build_failure_signal",
                    "title": "빌드 실패 징후",
                    "value": f"{build_runs}회 빌드 / 재수정 비율 {rework_ratio}%",
                    "context": "빌드 후 재수정이 많으면 빌드 단계 사전 체크(타입/린트) 자동화가 필요합니다.",
                },
                {
                    "category": "style_focus",
                    "title": "스타일 작업 비중",
                    "value": f"{_pct(style_count, total_files)}%",
                    "context": "스타일 파일 변경 비중입니다. 디자인 시스템 토큰 정합성을 확인하세요.",
                },
            ]
        )
    elif role == "data":
        notebook_count = sum(1 for path in lower_files if path.endswith(".ipynb"))
        pipeline_hits = sum(1 for cmd in lower_commands if any(token in cmd for token in ("pandas", "numpy", "sklearn")))
        insights.extend(
            [
                {
                    "category": "notebook_ratio",
                    "title": "노트북 작업 비중",
                    "value": f"{notebook_count}건",
                    "context": "실험 노트북 변경 건수입니다. 재현 가능성을 위해 스크립트화 여부를 점검하세요.",
                },
                {
                    "category": "pipeline_signal",
                    "title": "데이터 파이프라인 신호",
                    "value": f"{pipeline_hits}회",
                    "context": "pandas/numpy/sklearn 관련 실행 빈도입니다. 데이터 검증 자동화를 권장합니다.",
                },
            ]
        )
    elif role == "devops":
        deploy_count = sum(1 for cmd in lower_commands if ("docker push" in cmd or "kubectl apply" in cmd))
        infra_count = sum(
            1
            for path in changed_files
            if path.endswith((".yaml", ".yml", ".tf")) or Path(path).name == "Dockerfile"
        )
        insights.extend(
            [
                {
                    "category": "deploy_frequency",
                    "title": "배포 작업 빈도",
                    "value": f"{deploy_count}회",
                    "context": "docker push / kubectl apply 실행 빈도입니다. 배포 실패 로그와 함께 모니터링하세요.",
                },
                {
                    "category": "infra_changes",
                    "title": "인프라 변경",
                    "value": f"{infra_count}건",
                    "context": "IaC/컨테이너 설정 변경 건수입니다. 변경 승인 흐름을 점검하세요.",
                },
            ]
        )
    else:
        insights.append(
            {
                "category": "general",
                "title": "역할 신호 부족",
                "value": "unknown",
                "context": "역할 특화 패턴이 명확하지 않습니다. 명령어/파일 데이터가 더 필요합니다.",
            }
        )

    return insights


def _load_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _compute_growth(current: dict[str, Any], past: dict[str, Any] | None) -> dict[str, Any]:
    growth = {
        "new_tools": [],
        "increased_usage": [],
        "language_shift": None,
    }
    if not past:
        return growth

    current_usage = current.get("tool_usage", {})
    past_usage = past.get("tool_usage", {})
    if isinstance(current_usage, dict) and isinstance(past_usage, dict):
        current_tools = {k for k, v in current_usage.items() if int(v or 0) > 0}
        past_tools = {k for k, v in past_usage.items() if int(v or 0) > 0}
        growth["new_tools"] = sorted(current_tools - past_tools)

        increased: list[str] = []
        for tool, curr_count in current_usage.items():
            prev_count = int(past_usage.get(tool, 0) or 0)
            curr = int(curr_count or 0)
            if prev_count <= 0:
                continue
            if curr >= int(prev_count * 1.2):
                increased.append(tool)
        growth["increased_usage"] = sorted(increased)

    current_lang = current.get("profile", {}).get("language_breakdown", {})
    past_lang = past.get("profile", {}).get("language_breakdown", {})
    if isinstance(current_lang, dict) and isinstance(past_lang, dict):
        best_lang = None
        best_delta = 0.0
        for lang in set(current_lang.keys()) | set(past_lang.keys()):
            delta = float(current_lang.get(lang, 0.0) or 0.0) - float(past_lang.get(lang, 0.0) or 0.0)
            if abs(delta) >= 0.05 and abs(delta) > abs(best_delta):
                best_lang = lang
                best_delta = delta
        if best_lang:
            growth["language_shift"] = f"{best_lang} {best_delta * 100:+.0f}%"

    return growth


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    days_back = int(input_data.get("days_back", 30) or 30)
    scan_all_repos = bool(input_data.get("scan_all_repos", False))

    shell_entries = _load_shell_entries(days_back=days_back)
    full_commands = [str(entry.get("command", "")).strip() for entry in shell_entries if str(entry.get("command", "")).strip()]
    base_commands = [_extract_base_command(cmd) for cmd in full_commands if _extract_base_command(cmd)]
    command_counts: Counter[str] = Counter(base_commands)

    shell_data = {
        "entries": shell_entries,
        "full_commands": full_commands,
        "command_counts": command_counts,
        "top_commands": [{"command": cmd, "count": count} for cmd, count in command_counts.most_common(20)],
    }
    git_data = _collect_git_data(days_back=days_back, scan_all_repos=scan_all_repos, context=context)

    profile = _detect_tech_stack(shell_data, git_data)
    role_insights = _generate_role_insights(
        profile,
        {
            "changed_files": git_data.get("changed_files", []),
            "command_counts": command_counts,
            "full_commands": full_commands,
        },
    )

    today = datetime.now().date()
    snapshot_dir = Path("logs") / "developer_profiles"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    today_path = snapshot_dir / f"{today.isoformat()}.json"
    compare_path = snapshot_dir / f"{(today - timedelta(days=30)).isoformat()}.json"

    snapshot = {
        "date": today.isoformat(),
        "profile": profile,
        "tool_usage": dict(command_counts),
        "meta": {
            "days_back": days_back,
            "scan_all_repos": scan_all_repos,
            "commit_count": len(git_data.get("commits", [])),
        },
    }
    past_snapshot = _load_snapshot(compare_path)
    growth = _compute_growth(snapshot, past_snapshot)
    today_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        f"주 사용 언어는 {profile.get('primary_language', 'Unknown')}이며 "
        f"역할 힌트는 {profile.get('role_hint', 'unknown')}입니다."
    )

    return {
        "ok": True,
        "period": f"최근 {days_back}일",
        "profile": profile,
        "role_insights": role_insights,
        "growth": growth,
        "summary": summary,
    }


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
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
