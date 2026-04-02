from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import re
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_decode_text(content_b64: str) -> str:
    if not content_b64:
        return ""
    try:
        raw = base64.b64decode(content_b64.encode("ascii"), validate=False)
    except Exception:
        return ""
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if value:
            return value[:120]
    return ""


def _extract_fields(doc_type: str, rel_path: str, text: str) -> dict[str, Any]:
    lowered = text.lower()
    fields: dict[str, Any] = {"source_rel_path": rel_path}
    if doc_type == "business_registration":
        reg_match = re.search(r"\b\d{3}-\d{2}-\d{5}\b", text)
        fields["registration_number"] = reg_match.group(0) if reg_match else ""
        fields["entity_name"] = _first_non_empty_line(text)
    elif doc_type == "tax_invoice":
        invoice_match = re.search(r"(invoice|inv)[-_ ]?([a-z0-9]{3,})", lowered)
        amount_match = re.search(r"\b(\d{1,3}(?:,\d{3})+|\d+)\s*(krw|원|usd)?\b", lowered)
        fields["invoice_reference"] = invoice_match.group(0) if invoice_match else ""
        fields["amount_hint"] = amount_match.group(0) if amount_match else ""
    elif doc_type == "social_insurance":
        fields["status"] = "confirmed" if any(token in lowered for token in ("납부", "완료", "confirmed", "paid")) else ""
    elif doc_type == "investment_decision":
        if any(token in lowered for token in ("approve", "승인", "가결")):
            decision = "approved"
        elif any(token in lowered for token in ("reject", "부결", "반려")):
            decision = "rejected"
        else:
            decision = "unknown"
        fields["decision"] = decision
        fields["meeting_note_title"] = _first_non_empty_line(text)
    elif doc_type == "ir_deck":
        fields["deck_title"] = _first_non_empty_line(text)
        fields["has_roadmap_hint"] = any(token in lowered for token in ("roadmap", "전략", "plan", "go-to-market"))
    else:
        fields["preview"] = _first_non_empty_line(text)
    return fields


def normalize_collection_artifacts(
    *,
    startup_id: str,
    collection_id: str,
    artifacts_meta: list[dict[str, Any]],
    artifacts_payload: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload_by_path: dict[str, dict[str, Any]] = {}
    for row in artifacts_payload:
        if not isinstance(row, dict):
            continue
        rel_path = str(row.get("rel_path", "")).strip().replace("\\", "/")
        if rel_path:
            payload_by_path[rel_path] = row

    records: list[dict[str, Any]] = []
    for meta in artifacts_meta:
        if not isinstance(meta, dict):
            continue
        rel_path = str(meta.get("rel_path", "")).strip().replace("\\", "/")
        if not rel_path:
            continue
        artifact_id = str(meta.get("artifact_id", "")).strip() or f"sha256:{meta.get('sha256', '')}"
        doc_type = str(meta.get("doc_type", "unknown")).strip() or "unknown"
        confidence = float(meta.get("confidence", 0.0) or 0.0)
        payload = payload_by_path.get(rel_path, {})
        text = _safe_decode_text(str(payload.get("content_b64", "")))
        fields = _extract_fields(doc_type, rel_path, text)

        content_key = f"{collection_id}:{artifact_id}:{doc_type}"
        record_id = hashlib.sha256(content_key.encode("utf-8")).hexdigest()
        payload_json = {
            "schema_version": "vc_evidence_v1",
            "schema_type": doc_type,
            "source": {
                "rel_path": rel_path,
                "sha256": str(meta.get("sha256", "")).strip(),
                "size_bytes": int(meta.get("size_bytes", 0) or 0),
                "mtime": str(meta.get("mtime", "")).strip(),
                "artifact_id": artifact_id,
            },
            "fields": fields,
            "quality": {
                "classifier_confidence": round(confidence, 4),
                "text_length": len(text),
                "field_count": len([k for k, v in fields.items() if str(v).strip()]),
            },
            "normalized_at": _utc_now_iso(),
        }
        records.append(
            {
                "record_id": record_id,
                "startup_id": startup_id,
                "collection_id": collection_id,
                "artifact_id": artifact_id,
                "schema_type": doc_type,
                "payload": payload_json,
            }
        )
    return records
