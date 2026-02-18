from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import urllib.parse
import urllib.request
from typing import Any

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "github_pr_digest",
    "description": "Fetch open pull requests from GitHub and summarize them in Korean.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "GitHub repo in owner/name format",
            },
            "state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "default": "open",
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "description": "Maximum number of PRs to return",
            },
            "query": {
                "type": "string",
                "description": "Filter PR title/body by keyword",
            },
            "output": {
                "type": "string",
                "enum": ["text", "json"],
                "default": "text",
            },
        },
        "required": [],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _fetch_pulls(repo: str, state: str, limit: int, token: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"state": state, "per_page": str(limit)})
    url = f"https://api.github.com/repos/{repo}/pulls?{query}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "boramclaw-github-pr-digest")
    if token.strip():
        req.add_header("Authorization", f"Bearer {token.strip()}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise RuntimeError("GitHub API 응답 형식이 올바르지 않습니다.")
    return [item for item in parsed if isinstance(item, dict)]


def _to_summary(repo: str, pulls: list[dict[str, Any]]) -> str:
    now_text = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# GitHub PR Digest ({now_text})", f"저장소: {repo}", f"개수: {len(pulls)}", ""]
    if not pulls:
        lines.append("열린 PR이 없습니다.")
        return "\n".join(lines)
    for idx, pr in enumerate(pulls, start=1):
        title = str(pr.get("title", "")).strip()
        user = ""
        user_obj = pr.get("user")
        if isinstance(user_obj, dict):
            user = str(user_obj.get("login", "")).strip()
        url = str(pr.get("html_url", "")).strip()
        created = str(pr.get("created_at", "")).strip()
        draft = bool(pr.get("draft", False))
        lines.append(f"## {idx}. {title}")
        lines.append(f"- 작성자: {user or '-'}")
        lines.append(f"- 생성일: {created or '-'}")
        lines.append(f"- Draft: {'yes' if draft else 'no'}")
        lines.append(f"- 링크: {url or '-'}")
        lines.append("")
    return "\n".join(lines)


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    repo = str(input_data.get("repo") or os.getenv("GITHUB_DEFAULT_REPO") or "").strip()
    if not repo or "/" not in repo:
        return {
            "ok": False,
            "error": "repo 입력이 필요합니다. 예: owner/repo",
        }

    state = str(input_data.get("state", "open")).strip().lower()
    if state not in {"open", "closed", "all"}:
        state = "open"
    limit = max(1, min(int(input_data.get("limit", 5) or 5), 30))
    query = str(input_data.get("query", "")).strip().lower()
    output = str(input_data.get("output", "text")).strip().lower()
    token = str(os.getenv("GITHUB_TOKEN") or "")

    pulls = _fetch_pulls(repo=repo, state=state, limit=limit, token=token)
    if query:
        filtered: list[dict[str, Any]] = []
        for pr in pulls:
            hay = f"{pr.get('title', '')} {pr.get('body', '')}".lower()
            if query in hay:
                filtered.append(pr)
        pulls = filtered

    records: list[dict[str, Any]] = []
    for pr in pulls:
        user = pr.get("user") if isinstance(pr.get("user"), dict) else {}
        records.append(
            {
                "number": pr.get("number"),
                "title": pr.get("title", ""),
                "author": user.get("login", "") if isinstance(user, dict) else "",
                "created_at": pr.get("created_at", ""),
                "url": pr.get("html_url", ""),
                "draft": bool(pr.get("draft", False)),
            }
        )

    summary = _to_summary(repo=repo, pulls=pulls)
    payload = {
        "ok": True,
        "repo": repo,
        "count": len(records),
        "state": state,
        "summary": summary,
        "pulls": records,
    }
    if output == "json":
        return payload
    return {
        "ok": True,
        "repo": repo,
        "count": len(records),
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="github_pr_digest cli")
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
        print(json.dumps(run(input_data, context), ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
