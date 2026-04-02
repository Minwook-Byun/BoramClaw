from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.dispatch import dispatch_approval
from vc_platform.service import get_store


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_approval_queue",
    "description": "Manage VC approval queue and trigger gated dispatch.",
    "version": __version__,
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["pending", "approve", "reject", "status"]},
            "startup_id": {"type": "string"},
            "approval_id": {"type": "string"},
            "approver": {"type": "string"},
            "reason": {"type": "string"},
            "auto_dispatch": {"type": "boolean"},
            "dry_run_dispatch": {"type": "boolean"},
            "force_high_risk": {"type": "boolean"},
        },
        "required": ["action"],
    },
}


def _is_expired(expires_at: str) -> bool:
    value = expires_at.strip()
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc) <= datetime.now(timezone.utc)


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action", "")).strip().lower()
    if not action:
        return {"success": False, "error": "action is required"}
    store = get_store(context)

    if action == "pending":
        startup_id = str(input_data.get("startup_id", "")).strip().lower() or None
        rows = store.list_pending_approvals(startup_id=startup_id, limit=200)
        risk_breakdown = {"low": 0, "medium": 0, "high": 0}
        for row in rows:
            signoffs = store.list_approval_signoffs(approval_id=str(row.get("approval_id", "")))
            row["signoffs"] = signoffs
            row["signoff_count"] = len(signoffs)
            level = str(row.get("risk_level", "low")).strip().lower()
            if level not in risk_breakdown:
                level = "low"
            risk_breakdown[level] += 1
        return {
            "success": True,
            "action": action,
            "count": len(rows),
            "risk_breakdown": risk_breakdown,
            "pending": rows,
        }

    approval_id = str(input_data.get("approval_id", "")).strip()
    if not approval_id:
        return {"success": False, "error": "approval_id is required"}
    row = store.get_approval(approval_id)
    if row is None:
        return {"success": False, "error": f"approval not found: {approval_id}"}

    if action == "status":
        signoffs = store.list_approval_signoffs(approval_id=approval_id)
        return {"success": True, "action": action, "approval": row, "signoffs": signoffs, "signoff_count": len(signoffs)}

    if action == "reject":
        reason = str(input_data.get("reason", "")).strip() or "rejected"
        approver = str(input_data.get("approver", "")).strip() or "vc_operator"
        store.update_approval_status(
            approval_id=approval_id,
            status="rejected",
            approver=approver,
            reason=reason,
        )
        updated = store.get_approval(approval_id)
        return {"success": True, "action": action, "approval": updated}

    if action != "approve":
        return {"success": False, "error": f"unsupported action: {action}"}

    approver = str(input_data.get("approver", "")).strip() or str((os.getenv("VC_APPROVER_ID") or "").strip()) or "vc_operator"
    if _is_expired(str(row.get("expires_at", ""))):
        if str(row.get("status", "")).strip().lower() == "pending":
            store.update_approval_status(
                approval_id=approval_id,
                status="expired",
                approver=approver,
                reason="approval ttl exceeded",
            )
        return {"success": False, "error": f"approval expired: {approval_id}", "approval": store.get_approval(approval_id)}

    force_high_risk = bool(input_data.get("force_high_risk", False))
    risk_level = str(row.get("risk_level", "low")).strip().lower()
    if risk_level == "high" and not force_high_risk:
        return {
            "success": False,
            "error": "high-risk approval requires force_high_risk=true",
            "approval": row,
        }

    high_risk_signoffs: list[dict[str, Any]] = []
    if risk_level == "high":
        store.add_approval_signoff(approval_id=approval_id, approver=approver)
        high_risk_signoffs = store.list_approval_signoffs(approval_id=approval_id)
        unique_approvers = []
        for item in high_risk_signoffs:
            name = str(item.get("approver", "")).strip()
            if name and name not in unique_approvers:
                unique_approvers.append(name)
        if len(unique_approvers) < 2:
            store.update_approval_status(
                approval_id=approval_id,
                status="pending",
                approver=",".join(unique_approvers),
                reason="high-risk waiting second approver",
            )
            return {
                "success": True,
                "action": action,
                "requires_second_approval": True,
                "signoff_count": len(unique_approvers),
                "signoffs": high_risk_signoffs,
                "approval": store.get_approval(approval_id),
            }
        approver = ",".join(unique_approvers)

    status = str(row.get("status", "")).strip().lower()
    if status == "pending":
        store.update_approval_status(
            approval_id=approval_id,
            status="approved",
            approver=approver,
            reason="",
        )
    elif status not in {"approved", "dispatched"}:
        return {"success": False, "error": f"cannot approve from current status: {status}"}

    auto_dispatch = bool(input_data.get("auto_dispatch", True))
    if not auto_dispatch:
        return {
            "success": True,
            "action": action,
            "approval": store.get_approval(approval_id),
            "signoffs": high_risk_signoffs,
            "dispatched": False,
        }

    dry_run_default = not bool((os.getenv("VC_SMTP_HOST") or "").strip())
    dry_run_dispatch = bool(input_data.get("dry_run_dispatch", dry_run_default))
    dispatched = dispatch_approval(approval_id=approval_id, context=context, dry_run=dry_run_dispatch)
    return {
        "success": bool(dispatched.get("success", False)),
        "action": action,
        "approval": store.get_approval(approval_id),
        "signoffs": high_risk_signoffs,
        "dispatch_result": dispatched,
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_approval_queue cli")
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
