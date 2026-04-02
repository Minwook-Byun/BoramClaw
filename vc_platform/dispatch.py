from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .service import get_registry, get_store, resolve_workdir


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _build_email_body(*, approval: dict[str, Any], collection: dict[str, Any] | None) -> str:
    payload = approval.get("payload_json", {})
    if not isinstance(payload, dict):
        payload = {}
    summary = {}
    if isinstance(collection, dict):
        summary = collection.get("summary_json", {})
        if not isinstance(summary, dict):
            summary = {}
    lines = [
        "[OpenClaw VC Report]",
        f"startup_id: {approval.get('startup_id')}",
        f"approval_id: {approval.get('approval_id')}",
        f"collection_id: {approval.get('collection_id')}",
        f"risk_level: {approval.get('risk_level', 'low')}",
        f"risk_score: {approval.get('risk_score', 0.0)}",
        f"risk_reasons: {json.dumps(approval.get('risk_reasons_json', []), ensure_ascii=False)}",
        "",
        "Summary",
        f"- artifact_count: {summary.get('artifact_count', 0)}",
        f"- total_size_bytes: {summary.get('total_size_bytes', 0)}",
        f"- doc_types: {json.dumps(summary.get('doc_types', {}), ensure_ascii=False)}",
        "",
        f"metadata_path: {payload.get('metadata_path', '')}",
    ]
    return "\n".join(lines).strip() + "\n"


def _smtp_send(
    *,
    recipients: list[str],
    subject: str,
    body: str,
) -> tuple[bool, str]:
    host = (os.getenv("VC_SMTP_HOST") or "").strip()
    if not host:
        return False, "VC_SMTP_HOST not configured"
    port_raw = (os.getenv("VC_SMTP_PORT") or "587").strip()
    user = (os.getenv("VC_SMTP_USER") or "").strip()
    password = os.getenv("VC_SMTP_PASSWORD") or ""
    mail_from = (os.getenv("VC_SMTP_FROM") or user or "openclaw-vc@localhost").strip()
    use_tls = _bool_env("VC_SMTP_TLS", True)
    try:
        port = int(port_raw)
    except ValueError:
        port = 587

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
    return True, f"sent via smtp://{host}:{port}"


def dispatch_approval(
    *,
    approval_id: str,
    context: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    store = get_store(context)
    registry = get_registry(context)

    approval = store.get_approval(approval_id)
    if approval is None:
        return {"success": False, "error": f"approval not found: {approval_id}"}
    status = str(approval.get("status", "")).strip().lower()
    if status not in {"approved", "dispatched"}:
        return {"success": False, "error": f"approval status must be approved/dispatched, got={status}"}

    payload = approval.get("payload_json", {})
    if not isinstance(payload, dict):
        payload = {}
    startup_id = str(approval.get("startup_id", "")).strip().lower()
    if not startup_id:
        return {"success": False, "error": "startup_id not found in approval row"}

    tenant = registry.get(startup_id) or {}
    recipients = payload.get("email_recipients", [])
    if not isinstance(recipients, list) or not recipients:
        recipients = tenant.get("email_recipients", [])
    if not isinstance(recipients, list) or not recipients:
        return {"success": False, "error": "no email recipients configured"}
    recipients = [str(item).strip() for item in recipients if str(item).strip()]
    if not recipients:
        return {"success": False, "error": "no valid recipients"}

    collection_id = str(approval.get("collection_id", "")).strip()
    collection = store.get_collection(collection_id) if collection_id else None
    body = _build_email_body(approval=approval, collection=collection)
    subject = f"[OpenClaw][{startup_id}] Collection {collection_id}"

    if dry_run:
        return {
            "success": True,
            "sent": False,
            "dry_run": True,
            "approval_id": approval_id,
            "subject": subject,
            "recipients": recipients,
            "body_preview": body[:1000],
        }

    sent, detail = _smtp_send(recipients=recipients, subject=subject, body=body)
    if not sent:
        return {
            "success": False,
            "sent": False,
            "approval_id": approval_id,
            "error": detail,
        }

    store.update_approval_status(
        approval_id=approval_id,
        status="dispatched",
        approver=str(approval.get("approver", "") or ""),
    )
    if collection_id:
        store.set_collection_status(collection_id, "dispatched")

    metadata_path = str(payload.get("metadata_path", "")).strip()
    metadata_abs = ""
    if metadata_path:
        workdir = resolve_workdir(context)
        metadata_abs = str((workdir / Path(metadata_path)).resolve())

    return {
        "success": True,
        "sent": True,
        "approval_id": approval_id,
        "collection_id": collection_id,
        "subject": subject,
        "recipients": recipients,
        "transport": detail,
        "metadata_path": metadata_path,
        "metadata_abs": metadata_abs,
    }
