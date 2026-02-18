from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any
import urllib.request
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "arxiv_daily_digest",
    "description": "Fetch and summarize recent arXiv papers by keywords.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional keyword list. If omitted, fetch latest papers without keyword filter.",
            },
            "max_papers": {"type": "integer", "minimum": 1, "maximum": 50},
            "days_back": {"type": "integer", "minimum": 1, "maximum": 30},
            "output": {"type": "string", "enum": ["text", "file"], "default": "text"},
            "output_file": {"type": "string"},
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


def _fetch_arxiv_entries(keywords: list[str], max_papers: int) -> list[dict[str, str]]:
    if keywords:
        query = " OR ".join([f'all:\"{kw}\"' for kw in keywords])
    else:
        query = "cat:cs.AI OR cat:cs.LG"
    encoded_query = quote_plus(query)
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query={encoded_query}&sortBy=submittedDate&sortOrder=descending&max_results={max_papers}"
    )
    try:
        import feedparser  # type: ignore

        feed = feedparser.parse(url)
        entries: list[dict[str, str]] = []
        for item in getattr(feed, "entries", []) or []:
            title = str(getattr(item, "title", "")).strip()
            summary = str(getattr(item, "summary", "")).strip()
            link = str(getattr(item, "link", "")).strip()
            published = str(getattr(item, "published", "")).strip()
            if not title:
                continue
            entries.append(
                {
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published,
                }
            )
        return entries
    except Exception:
        # Fallback to stdlib-only parser so this tool works without extra packages.
        with urllib.request.urlopen(url, timeout=20) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries: list[dict[str, str]] = []
        for entry in root.findall("atom:entry", ns):
            title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
            summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
            published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
            link = ""
            for link_el in entry.findall("atom:link", ns):
                rel = (link_el.attrib.get("rel") or "").strip()
                href = (link_el.attrib.get("href") or "").strip()
                if href and (not rel or rel == "alternate"):
                    link = href
                    break
            if not title:
                continue
            entries.append(
                {
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published,
                }
            )
        return entries


def _filter_recent(entries: list[dict[str, str]], days_back: int) -> list[dict[str, str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days_back)))
    filtered: list[dict[str, str]] = []
    for item in entries:
        published = item.get("published", "")
        if not published:
            filtered.append(item)
            continue
        try:
            dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            filtered.append(item)
            continue
        if dt >= cutoff:
            filtered.append(item)
    return filtered


def _summarize(entries: list[dict[str, str]], keywords: list[str]) -> str:
    if not entries:
        return "No recent arXiv papers matched the keywords."
    # Simple local fallback summary. Can be upgraded to LLM summarization later.
    lines = [f"# arXiv Daily Digest ({datetime.now().strftime('%Y-%m-%d')})", ""]
    lines.append(f"Keywords: {', '.join(keywords) if keywords else '(none)'}")
    lines.append("")
    for idx, item in enumerate(entries, start=1):
        lines.append(f"## {idx}. {item.get('title', '(no title)')}")
        lines.append(f"- Published: {item.get('published', '')}")
        lines.append(f"- Link: {item.get('link', '')}")
        summary = item.get("summary", "").replace("\n", " ").strip()
        lines.append(f"- Summary: {summary[:400]}")
        lines.append("")
    return "\n".join(lines)


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    keywords = input_data.get("keywords", [])
    if keywords is None:
        keywords = []
    if not isinstance(keywords, list):
        raise ValueError("keywords must be a list of strings.")
    normalized_keywords = [str(x).strip() for x in keywords if str(x).strip()]
    max_papers = int(input_data.get("max_papers", 10))
    days_back = int(input_data.get("days_back", 1))
    output = str(input_data.get("output", "text")).strip().lower()
    output_file = str(input_data.get("output_file", "")).strip()

    entries = _fetch_arxiv_entries(normalized_keywords, max_papers=max(1, min(max_papers, 50)))
    entries = _filter_recent(entries, days_back=days_back)
    summary = _summarize(entries, normalized_keywords)

    if output == "file":
        if not output_file:
            output_file = f"logs/arxiv_digest_{datetime.now().strftime('%Y%m%d')}.md"
        target = Path(output_file)
        if not target.is_absolute():
            workdir = Path(str(context.get("workdir", ".")))
            target = (workdir / target).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(summary, encoding="utf-8")
        return {
            "ok": True,
            "output": "file",
            "output_file": str(target),
            "paper_count": len(entries),
        }

    return {
        "ok": True,
        "output": "text",
        "paper_count": len(entries),
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="arxiv_daily_digest cli")
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
