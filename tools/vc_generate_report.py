from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import get_store, resolve_workdir


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_generate_report",
    "description": "Generate daily/weekly/range report from VC collection DB.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "startup_id": {"type": "string"},
            "mode": {"type": "string", "description": "daily|weekly|range:YYYY-MM-DD,YYYY-MM-DD"},
            "collection_id": {"type": "string"},
            "output_file": {"type": "string"},
        },
        "required": ["startup_id"],
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _mode_to_window(mode: str) -> tuple[str | None, str | None]:
    normalized = mode.strip().lower()
    now = _utc_now()
    if normalized in {"", "daily", "today"}:
        return (now - timedelta(days=1)).isoformat(), now.isoformat()
    if normalized in {"weekly", "week", "7d"}:
        return (now - timedelta(days=7)).isoformat(), now.isoformat()
    if normalized.startswith("range:"):
        payload = normalized[len("range:") :]
        parts = [item.strip() for item in payload.split(",")]
        if len(parts) == 2 and parts[0] and parts[1]:
            return f"{parts[0]}T00:00:00+00:00", f"{parts[1]}T23:59:59+00:00"
    return None, None


def _render_markdown(
    *,
    startup_id: str,
    mode: str,
    collections: list[dict[str, Any]],
    artifact_count: int,
    total_bytes: int,
    doc_types: Counter[str],
    normalized_count: int,
    normalized_schemas: Counter[str],
    approval_risk_distribution: Counter[str],
) -> str:
    lines = [
        f"# VC Report - {startup_id}",
        "",
        f"- Mode: {mode}",
        f"- Generated At (UTC): {_utc_now().isoformat()}",
        f"- Collections: {len(collections)}",
        f"- Artifacts: {artifact_count}",
        f"- Total Size: {total_bytes:,} bytes",
        f"- Normalized Records: {normalized_count}",
        "",
        "## Doc Type Distribution",
    ]
    if not doc_types:
        lines.append("- (none)")
    else:
        for doc_type, count in doc_types.most_common():
            lines.append(f"- {doc_type}: {count}")

    lines.append("")
    lines.append("## Normalized Schema Coverage")
    if not normalized_schemas:
        lines.append("- (none)")
    else:
        for schema_type, count in normalized_schemas.most_common():
            lines.append(f"- {schema_type}: {count}")

    lines.append("")
    lines.append("## Approval Risk Distribution")
    if not approval_risk_distribution:
        lines.append("- (none)")
    else:
        for level in ("high", "medium", "low"):
            lines.append(f"- {level}: {approval_risk_distribution.get(level, 0)}")

    lines.append("")
    lines.append("## Recent Collections")
    if not collections:
        lines.append("- (none)")
    else:
        for row in collections[:10]:
            summary = row.get("summary_json", {})
            artifact_size = 0
            artifact_total = 0
            if isinstance(summary, dict):
                artifact_size = int(summary.get("total_size_bytes", 0) or 0)
                artifact_total = int(summary.get("artifact_count", 0) or 0)
            lines.append(
                f"- {row.get('collection_id')} | status={row.get('status')} | "
                f"artifacts={artifact_total} | size={artifact_size:,} bytes | created_at={row.get('created_at')}"
            )
    return "\n".join(lines).strip() + "\n"


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    startup_id = str(input_data.get("startup_id", "")).strip().lower()
    if not startup_id:
        return {"success": False, "error": "startup_id is required"}
    mode = str(input_data.get("mode", "weekly")).strip() or "weekly"
    collection_id = str(input_data.get("collection_id", "")).strip()

    store = get_store(context)
    window_from = None
    window_to = None
    if collection_id:
        row = store.get_collection(collection_id)
        if row is None:
            return {"success": False, "error": f"collection not found: {collection_id}"}
        collections = [row]
    else:
        window_from, window_to = _mode_to_window(mode)
        collections = store.list_collections(
            startup_id=startup_id,
            window_from=window_from,
            window_to=window_to,
            limit=500,
        )

    artifact_count = 0
    total_bytes = 0
    doc_types: Counter[str] = Counter()
    normalized_count = 0
    normalized_schemas: Counter[str] = Counter()
    for row in collections:
        row_collection_id = str(row.get("collection_id", ""))
        artifacts = store.list_artifacts(collection_id=row_collection_id)
        artifact_count += len(artifacts)
        for artifact in artifacts:
            total_bytes += int(artifact.get("size_bytes", 0) or 0)
            doc_types[str(artifact.get("doc_type", "unknown"))] += 1
        normalized_rows = store.list_normalized_records(collection_id=row_collection_id, limit=5000)
        normalized_count += len(normalized_rows)
        for norm in normalized_rows:
            normalized_schemas[str(norm.get("schema_type", "unknown"))] += 1

    approvals = store.list_approvals(
        startup_id=startup_id,
        window_from=window_from,
        window_to=window_to,
        limit=1000,
    )
    approval_risk_distribution: Counter[str] = Counter()
    for row in approvals:
        approval_risk_distribution[str(row.get("risk_level", "low")).strip().lower() or "low"] += 1

    markdown = _render_markdown(
        startup_id=startup_id,
        mode=mode,
        collections=collections,
        artifact_count=artifact_count,
        total_bytes=total_bytes,
        doc_types=doc_types,
        normalized_count=normalized_count,
        normalized_schemas=normalized_schemas,
        approval_risk_distribution=approval_risk_distribution,
    )
    output_file_raw = str(input_data.get("output_file", "")).strip()
    output_file = ""
    if output_file_raw:
        workdir = resolve_workdir(context)
        target = (workdir / output_file_raw).resolve()
        try:
            target.relative_to(workdir)
        except ValueError:
            return {"success": False, "error": "output_file must be inside workdir"}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        output_file = str(target.relative_to(workdir))

    return {
        "success": True,
        "startup_id": startup_id,
        "mode": mode,
        "collections": len(collections),
        "artifact_count": artifact_count,
        "total_size_bytes": total_bytes,
        "normalized_record_count": normalized_count,
        "normalized_schema_distribution": dict(normalized_schemas),
        "approval_risk_distribution": dict(approval_risk_distribution),
        "doc_type_distribution": dict(doc_types),
        "report_markdown": markdown,
        "output_file": output_file,
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_generate_report cli")
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
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
