from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import median
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import get_registry, get_store, period_to_days, resolve_workdir


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_ops_dashboard",
    "description": "Build VC operations dashboard metrics by tenant and time window.",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "startup_id": {"type": "string", "description": "optional tenant filter"},
            "window": {"type": "string", "description": "7d|30d|90d", "default": "30d"},
            "output_file": {"type": "string"},
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# VC Ops Dashboard",
        "",
        f"- Generated At (UTC): {payload.get('generated_at', '')}",
        f"- Window: {payload.get('window', '')}",
        f"- Tenants: {payload.get('tenant_count', 0)}",
        f"- Collections: {payload.get('collection_total', 0)}",
        f"- Collection Success Rate: {payload.get('collection_success_rate', 0.0):.2%}",
        f"- Verification Failure Rate: {payload.get('verification_failure_rate', 0.0):.2%}",
        f"- Unknown Doc Ratio: {payload.get('unknown_doc_ratio', 0.0):.2%}",
        f"- Median Approval Minutes: {payload.get('median_approval_minutes', 0.0):.1f}",
        f"- Dispatch Success Rate: {payload.get('dispatch_success_rate', 0.0):.2%}",
        "",
        "## Approval Risk Distribution",
    ]
    risk = payload.get("approval_risk_distribution", {})
    if not isinstance(risk, dict) or not risk:
        lines.append("- (none)")
    else:
        for level in ("high", "medium", "low"):
            lines.append(f"- {level}: {int(risk.get(level, 0) or 0)}")
    lines.append("")
    lines.append("## Tenant Error Rates")
    tenant_error_rates = payload.get("tenant_error_rates", {})
    if not isinstance(tenant_error_rates, dict) or not tenant_error_rates:
        lines.append("- (none)")
    else:
        for startup_id, row in tenant_error_rates.items():
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {startup_id}: collections={int(row.get('collections', 0) or 0)}, "
                f"verification_failed={int(row.get('verification_failed', 0) or 0)}, "
                f"error_rate={float(row.get('error_rate', 0.0) or 0.0):.2%}"
            )
    return "\n".join(lines).strip() + "\n"


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    registry = get_registry(context)
    store = get_store(context)

    requested_startup_id = str(input_data.get("startup_id", "")).strip().lower()
    window = str(input_data.get("window", "30d")).strip().lower() or "30d"
    days = period_to_days(window)
    now = _utc_now()
    window_from = (now - timedelta(days=days)).isoformat()
    window_to = now.isoformat()

    tenants = registry.list_tenants(active_only=True)
    if requested_startup_id:
        tenants = [row for row in tenants if str(row.get("startup_id", "")).strip().lower() == requested_startup_id]
    if not tenants:
        return {"success": False, "error": "no tenant found for requested scope"}

    collection_total = 0
    collection_success = 0
    verification_failed = 0
    artifact_total = 0
    unknown_total = 0
    approval_risk_distribution: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    tenant_error_rates: dict[str, dict[str, Any]] = {}
    approval_minutes: list[float] = []
    approval_total = 0
    dispatched_total = 0

    for tenant in tenants:
        startup_id = str(tenant.get("startup_id", "")).strip().lower()
        collections = store.list_collections(
            startup_id=startup_id,
            window_from=window_from,
            window_to=window_to,
            limit=2000,
        )
        startup_total = len(collections)
        startup_failed = 0
        collection_total += startup_total
        for col in collections:
            status = str(col.get("status", "")).strip().lower()
            if status == "verification_failed":
                verification_failed += 1
                startup_failed += 1
            else:
                collection_success += 1
            artifacts = store.list_artifacts(collection_id=str(col.get("collection_id", "")))
            artifact_total += len(artifacts)
            for item in artifacts:
                if str(item.get("doc_type", "unknown")).strip().lower() == "unknown":
                    unknown_total += 1
        tenant_error_rates[startup_id] = {
            "collections": startup_total,
            "verification_failed": startup_failed,
            "error_rate": (startup_failed / startup_total) if startup_total else 0.0,
        }

        approvals = store.list_approvals(
            startup_id=startup_id,
            window_from=window_from,
            window_to=window_to,
            limit=5000,
        )
        for approval in approvals:
            level = str(approval.get("risk_level", "low")).strip().lower()
            if level not in approval_risk_distribution:
                level = "low"
            approval_risk_distribution[level] += 1

            status = str(approval.get("status", "")).strip().lower()
            if status in {"approved", "dispatched"}:
                approval_total += 1
            if status == "dispatched":
                dispatched_total += 1

            req = _parse_iso(str(approval.get("requested_at", "")))
            app = _parse_iso(str(approval.get("approved_at", "")))
            if req and app and app >= req:
                approval_minutes.append((app - req).total_seconds() / 60.0)

    collection_success_rate = (collection_success / collection_total) if collection_total else 0.0
    verification_failure_rate = (verification_failed / collection_total) if collection_total else 0.0
    unknown_doc_ratio = (unknown_total / artifact_total) if artifact_total else 0.0
    dispatch_success_rate = (dispatched_total / approval_total) if approval_total else 0.0
    median_approval_minutes = median(approval_minutes) if approval_minutes else 0.0

    result = {
        "success": True,
        "generated_at": now.isoformat(),
        "window": window,
        "window_from": window_from,
        "window_to": window_to,
        "tenant_count": len(tenants),
        "collection_total": collection_total,
        "collection_success_rate": round(collection_success_rate, 4),
        "verification_failure_rate": round(verification_failure_rate, 4),
        "unknown_doc_ratio": round(unknown_doc_ratio, 4),
        "median_approval_minutes": round(float(median_approval_minutes), 2),
        "dispatch_success_rate": round(dispatch_success_rate, 4),
        "approval_risk_distribution": approval_risk_distribution,
        "tenant_error_rates": tenant_error_rates,
    }
    markdown = _markdown(result)
    result["dashboard_markdown"] = markdown

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
    result["output_file"] = output_file
    return result


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_ops_dashboard cli")
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
