from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import re
import sys
from typing import Any
import urllib.request

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "semantic_web_snapshot",
    "description": "Fetch a web page and return semantic snapshot (title/headings/links/text excerpt).",
    "version": "1.0.0",
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (http/https)"},
            "max_headings": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
            "max_links": {"type": "integer", "minimum": 1, "maximum": 200, "default": 40},
            "max_text_chars": {"type": "integer", "minimum": 200, "maximum": 12000, "default": 3000},
            "timeout_seconds": {"type": "integer", "minimum": 3, "maximum": 60, "default": 20},
        },
        "required": ["url"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


class _SemanticParser(HTMLParser):
    def __init__(self, max_headings: int, max_links: int, max_text_chars: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_headings = max_headings
        self.max_links = max_links
        self.max_text_chars = max_text_chars
        self.title_parts: list[str] = []
        self.headings: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.landmarks: dict[str, int] = {
            "header": 0,
            "nav": 0,
            "main": 0,
            "article": 0,
            "section": 0,
            "aside": 0,
            "footer": 0,
        }
        self._current_heading: str | None = None
        self._current_link_href: str | None = None
        self._current_link_text: list[str] = []
        self._in_title = False
        self._skip_depth = 0
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self.landmarks:
            self.landmarks[tag_lower] += 1
        if tag_lower in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag_lower == "title":
            self._in_title = True
            return
        if tag_lower in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._current_heading = tag_lower
            return
        if tag_lower == "a":
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value.strip()
                    break
            self._current_link_href = href
            self._current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"script", "style", "noscript"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag_lower == "title":
            self._in_title = False
            return
        if self._current_heading and tag_lower == self._current_heading:
            self._current_heading = None
            return
        if tag_lower == "a" and self._current_link_href is not None:
            if len(self.links) < self.max_links:
                text = _normalize_space(" ".join(self._current_link_text))
                href = self._current_link_href
                if href:
                    self.links.append({"text": text, "href": href})
            self._current_link_href = None
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = _normalize_space(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
            return
        if self._current_heading and len(self.headings) < self.max_headings:
            self.headings.append({"level": self._current_heading, "text": text})
        if self._current_link_href is not None:
            self._current_link_text.append(text)
        if sum(len(x) for x in self._text_parts) < self.max_text_chars:
            self._text_parts.append(text)

    def snapshot(self) -> dict[str, Any]:
        title = _normalize_space(" ".join(self.title_parts))
        text_excerpt = _normalize_space(" ".join(self._text_parts))[: self.max_text_chars]
        return {
            "title": title,
            "headings": self.headings,
            "links": self.links,
            "landmarks": self.landmarks,
            "text_excerpt": text_excerpt,
        }


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _fetch_html(url: str, timeout_seconds: int) -> tuple[str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "BoramClaw-SemanticSnapshot/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        final_url = str(resp.geturl())
        raw = resp.read()
        content_type = str(resp.headers.get("Content-Type", ""))
    charset = "utf-8"
    if "charset=" in content_type.lower():
        charset = content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    html = raw.decode(charset, errors="replace")
    return html, final_url


def _format_snapshot_markdown(url: str, snap: dict[str, Any]) -> str:
    lines = [f"# Semantic Snapshot", "", f"- URL: {url}"]
    title = str(snap.get("title", "")).strip()
    if title:
        lines.append(f"- Title: {title}")
    landmarks = snap.get("landmarks", {})
    if isinstance(landmarks, dict):
        parts = [f"{k}={v}" for k, v in landmarks.items() if int(v or 0) > 0]
        if parts:
            lines.append(f"- Landmarks: {', '.join(parts)}")
    lines.append("")
    headings = snap.get("headings", [])
    if isinstance(headings, list) and headings:
        lines.append("## Headings")
        for item in headings[:20]:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('level', '')}: {item.get('text', '')}")
        lines.append("")
    links = snap.get("links", [])
    if isinstance(links, list) and links:
        lines.append("## Links")
        for item in links[:20]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip() or "(no text)"
            href = str(item.get("href", "")).strip()
            lines.append(f"- {text} -> {href}")
        lines.append("")
    excerpt = str(snap.get("text_excerpt", "")).strip()
    if excerpt:
        lines.append("## Text Excerpt")
        lines.append(excerpt)
    return "\n".join(lines).strip()


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    url = str(input_data.get("url", "")).strip()
    if not url:
        return {"ok": False, "error": "url is required"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": "url must start with http:// or https://"}

    max_headings = max(1, min(int(input_data.get("max_headings", 30)), 100))
    max_links = max(1, min(int(input_data.get("max_links", 40)), 200))
    max_text_chars = max(200, min(int(input_data.get("max_text_chars", 3000)), 12000))
    timeout_seconds = max(3, min(int(input_data.get("timeout_seconds", 20)), 60))

    html, final_url = _fetch_html(url, timeout_seconds=timeout_seconds)
    parser = _SemanticParser(
        max_headings=max_headings,
        max_links=max_links,
        max_text_chars=max_text_chars,
    )
    parser.feed(html)
    snap = parser.snapshot()
    markdown = _format_snapshot_markdown(final_url, snap)

    return {
        "ok": True,
        "url": url,
        "final_url": final_url,
        "title": snap.get("title", ""),
        "headings": snap.get("headings", []),
        "links": snap.get("links", []),
        "landmarks": snap.get("landmarks", {}),
        "text_excerpt": snap.get("text_excerpt", ""),
        "snapshot_markdown": markdown,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="semantic_web_snapshot cli")
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

