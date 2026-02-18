from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "browser_research_digest",
    "description": "Chrome/Safari 브라우저 히스토리를 분석하여 리서치 세션을 클러스터링하고 요약합니다.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "hours": {
                "type": "integer",
                "description": "분석할 기간 (시간 단위, 기본 24)",
            },
            "browser": {
                "type": "string",
                "enum": ["chrome", "safari", "all"],
                "description": "브라우저 선택 (기본: all)",
            },
            "min_cluster_size": {
                "type": "integer",
                "description": "클러스터 최소 페이지 수 (기본 3)",
            },
        },
        "required": [],
    },
}

# Chrome history DB 경로 (macOS)
CHROME_HISTORY = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome/Default/History"
)
# Safari history DB 경로 (macOS)
SAFARI_HISTORY = os.path.expanduser(
    "~/Library/Safari/History.db"
)

# Chrome 타임스탬프: 1601-01-01로부터의 마이크로초
_CHROME_EPOCH = datetime(1601, 1, 1)
# Safari 타임스탬프: 2001-01-01로부터의 초
_SAFARI_EPOCH = datetime(2001, 1, 1)

# 무시할 도메인
_IGNORE_DOMAINS = {
    "localhost", "127.0.0.1", "newtab", "extensions",
    "chrome", "about", "blob", "data",
}


def _safe_copy_db(db_path: str) -> str | None:
    """브라우저가 잠근 DB를 임시 파일로 복사."""
    if not os.path.exists(db_path):
        return None
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(db_path, tmp)
        return tmp
    except (OSError, PermissionError):
        return None


def _query_chrome(hours: int) -> list[dict]:
    tmp = _safe_copy_db(CHROME_HISTORY)
    if not tmp:
        return []

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        chrome_cutoff = int((cutoff - _CHROME_EPOCH).total_seconds() * 1_000_000)

        conn = sqlite3.connect(tmp)
        cursor = conn.execute(
            """SELECT url, title, visit_count, last_visit_time
               FROM urls
               WHERE last_visit_time > ?
               ORDER BY last_visit_time DESC
               LIMIT 500""",
            (chrome_cutoff,),
        )
        rows = cursor.fetchall()
        conn.close()

        entries = []
        for url, title, visit_count, ts in rows:
            dt = _CHROME_EPOCH + timedelta(microseconds=ts)
            entries.append({
                "url": url,
                "title": title or "",
                "visit_count": visit_count,
                "timestamp": dt.isoformat(),
                "browser": "chrome",
            })
        return entries
    except (sqlite3.Error, OSError):
        return []
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _query_safari(hours: int) -> list[dict]:
    tmp = _safe_copy_db(SAFARI_HISTORY)
    if not tmp:
        return []

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        safari_cutoff = (cutoff - _SAFARI_EPOCH).total_seconds()

        conn = sqlite3.connect(tmp)
        cursor = conn.execute(
            """SELECT hi.url, hv.title, hv.visit_time
               FROM history_visits hv
               JOIN history_items hi ON hv.history_item = hi.id
               WHERE hv.visit_time > ?
               ORDER BY hv.visit_time DESC
               LIMIT 500""",
            (safari_cutoff,),
        )
        rows = cursor.fetchall()
        conn.close()

        entries = []
        for url, title, ts in rows:
            dt = _SAFARI_EPOCH + timedelta(seconds=ts)
            entries.append({
                "url": url,
                "title": title or "",
                "visit_count": 1,
                "timestamp": dt.isoformat(),
                "browser": "safari",
            })
        return entries
    except (sqlite3.Error, OSError):
        return []
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _cluster_by_domain(entries: list[dict], min_size: int) -> list[dict]:
    """도메인 기반 클러스터링."""
    domain_groups: dict[str, list[dict]] = defaultdict(list)

    for e in entries:
        try:
            parsed = urlparse(e["url"])
            domain = parsed.netloc.lower().replace("www.", "")
            if not domain or domain in _IGNORE_DOMAINS:
                continue
            domain_groups[domain].append(e)
        except Exception:
            continue

    clusters = []
    for domain, pages in sorted(domain_groups.items(),
                                 key=lambda x: len(x[1]), reverse=True):
        if len(pages) >= min_size:
            titles = [p["title"] for p in pages if p["title"]][:10]
            clusters.append({
                "domain": domain,
                "page_count": len(pages),
                "titles": titles,
                "first_visit": min(p["timestamp"] for p in pages),
                "last_visit": max(p["timestamp"] for p in pages),
            })

    return clusters[:15]


def _topic_clusters(entries: list[dict], min_size: int) -> list[dict]:
    """시간 기반 세션 클러스터링 (30분 간격)."""
    if not entries:
        return []

    # 타임스탬프 기준 정렬
    sorted_entries = sorted(entries, key=lambda e: e["timestamp"])

    sessions: list[list[dict]] = []
    current_session: list[dict] = [sorted_entries[0]]

    for e in sorted_entries[1:]:
        try:
            prev_ts = datetime.fromisoformat(current_session[-1]["timestamp"])
            curr_ts = datetime.fromisoformat(e["timestamp"])
            gap = (curr_ts - prev_ts).total_seconds()

            if gap > 1800:  # 30분 이상 간격 → 새 세션
                if len(current_session) >= min_size:
                    sessions.append(current_session)
                current_session = [e]
            else:
                current_session.append(e)
        except (ValueError, KeyError):
            current_session.append(e)

    if len(current_session) >= min_size:
        sessions.append(current_session)

    result = []
    for session in sessions[:10]:
        domains = set()
        titles = []
        for e in session:
            try:
                d = urlparse(e["url"]).netloc.replace("www.", "")
                if d and d not in _IGNORE_DOMAINS:
                    domains.add(d)
            except Exception:
                pass
            if e["title"]:
                titles.append(e["title"])

        result.append({
            "start_time": session[0]["timestamp"],
            "end_time": session[-1]["timestamp"],
            "page_count": len(session),
            "domains": sorted(domains)[:5],
            "sample_titles": titles[:5],
        })

    return result


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    hours = input_data.get("hours", 24)
    browser = input_data.get("browser", "all")
    min_cluster = input_data.get("min_cluster_size", 3)

    entries: list[dict] = []

    if browser in ("chrome", "all"):
        entries.extend(_query_chrome(hours))
    if browser in ("safari", "all"):
        entries.extend(_query_safari(hours))

    if not entries:
        return {
            "ok": True,
            "period": f"최근 {hours}시간",
            "total_pages": 0,
            "message": "브라우저 히스토리를 찾을 수 없습니다. Chrome 또는 Safari가 설치되어 있는지 확인하세요.",
        }

    # 중복 URL 제거 (가장 최근 방문만 유지)
    seen_urls: set[str] = set()
    unique_entries: list[dict] = []
    for e in entries:
        if e["url"] not in seen_urls:
            seen_urls.add(e["url"])
            unique_entries.append(e)

    domain_clusters = _cluster_by_domain(unique_entries, min_cluster)
    time_sessions = _topic_clusters(unique_entries, min_cluster)

    # 가장 많이 방문한 도메인 Top 5
    domain_count: defaultdict[str, int] = defaultdict(int)
    for e in unique_entries:
        try:
            d = urlparse(e["url"]).netloc.replace("www.", "")
            if d and d not in _IGNORE_DOMAINS:
                domain_count[d] += 1
        except Exception:
            pass
    top_domains = sorted(domain_count.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "ok": True,
        "period": f"최근 {hours}시간",
        "total_pages": len(unique_entries),
        "unique_domains": len(domain_count),
        "top_domains": [{"domain": d, "count": c} for d, c in top_domains],
        "domain_clusters": domain_clusters,
        "time_sessions": time_sessions,
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="browser_research_digest cli")
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
