from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import (
    build_signed_headers,
    get_crypto_store,
    get_registry,
    get_store,
    period_to_days,
    request_json,
    resolve_vault_root,
    resolve_workdir,
)
from vc_platform.normalizer import normalize_collection_artifacts
from vc_platform.policy import filter_artifacts_by_policy
from vc_platform.risk import assess_collection_risk


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_collect_bundle",
    "description": "VC multi-tenant data collection and encrypted bundle storage.",
    "version": __version__,
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register", "bind_folder", "collect", "status"],
                "description": "Action name",
            },
            "startup_id": {"type": "string"},
            "display_name": {"type": "string"},
            "gateway_url": {"type": "string"},
            "folder_alias": {"type": "string"},
            "gateway_secret": {"type": "string"},
            "period": {"type": "string", "description": "today|7d|30d"},
            "window_from": {"type": "string"},
            "window_to": {"type": "string"},
            "include_ocr": {"type": "boolean"},
            "max_artifacts": {"type": "integer", "minimum": 1, "maximum": 1000},
            "auto_verify": {"type": "boolean", "description": "Run integrity verification after collect (default: true)"},
        },
        "required": ["action", "startup_id"],
    },
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _default_window(period: str) -> tuple[str, str]:
    days = period_to_days(period)
    end = _now_utc()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _urljoin(base: str, path: str) -> str:
    cleaned = base.rstrip("/")
    return f"{cleaned}{path}"


def _collect_from_gateway(
    *,
    tenant: dict[str, Any],
    startup_id: str,
    request_id: str,
    window_from: str,
    window_to: str,
    include_ocr: bool,
    max_artifacts: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gateway_url = str(tenant.get("gateway_url", "")).strip()
    if not gateway_url:
        raise ValueError(f"tenant({startup_id}) has no gateway_url")
    folder_alias = str(tenant.get("folder_alias", "desktop_common")).strip() or "desktop_common"
    allowed_doc_types = tenant.get("allowed_doc_types", [])
    if not isinstance(allowed_doc_types, list):
        allowed_doc_types = []
    secret = str(tenant.get("gateway_secret", "")).strip()

    health = request_json(method="GET", url=_urljoin(gateway_url, "/health"), timeout=10)
    if not bool(health.get("ok", False)):
        raise RuntimeError(f"gateway health check failed: {health}")

    manifest_payload = {
        "startup_id": startup_id,
        "request_id": request_id,
        "window_from": window_from,
        "window_to": window_to,
        "doc_types": allowed_doc_types,
        "include_ocr": bool(include_ocr),
        "folder_alias": folder_alias,
        "max_artifacts": int(max_artifacts),
    }
    manifest_body = _json_bytes(manifest_payload)
    manifest_headers = build_signed_headers(secret, manifest_body)
    manifest = request_json(
        method="POST",
        url=_urljoin(gateway_url, "/manifest"),
        payload=manifest_payload,
        headers=manifest_headers,
        timeout=30,
    )
    artifacts_meta = manifest.get("artifacts", [])
    if not isinstance(artifacts_meta, list):
        artifacts_meta = []

    collected_meta: list[dict[str, Any]] = []
    collected_payload: list[dict[str, Any]] = []
    for item in artifacts_meta[:max_artifacts]:
        if not isinstance(item, dict):
            continue
        rel_path = str(item.get("rel_path", "")).strip()
        if not rel_path:
            continue

        content_payload = {
            "startup_id": startup_id,
            "request_id": request_id,
            "rel_path": rel_path,
        }
        content_body = _json_bytes(content_payload)
        content_headers = build_signed_headers(secret, content_body)
        response = request_json(
            method="POST",
            url=_urljoin(gateway_url, "/artifact-content"),
            payload=content_payload,
            headers=content_headers,
            timeout=30,
        )
        artifact = response.get("artifact", {})
        if not isinstance(artifact, dict):
            continue
        content_b64 = str(artifact.get("content_b64", ""))
        if not content_b64:
            continue
        raw = base64.b64decode(content_b64.encode("ascii"))
        digest = _sha256_bytes(raw)
        expected = str(item.get("sha256", "")).strip() or str(artifact.get("sha256", "")).strip()
        if expected and digest != expected:
            raise RuntimeError(f"sha256 mismatch: {rel_path}")

        normalized = {
            "artifact_id": str(item.get("artifact_id", f"sha256:{digest}")),
            "rel_path": rel_path,
            "size_bytes": int(item.get("size_bytes", len(raw)) or len(raw)),
            "mtime": str(item.get("mtime", "")),
            "sha256": digest,
            "doc_type": str(item.get("doc_type", "unknown")),
            "confidence": float(item.get("confidence", 0.0) or 0.0),
        }
        collected_meta.append(normalized)
        collected_payload.append(
            {
                "rel_path": rel_path,
                "sha256": digest,
                "content_b64": content_b64,
            }
        )
    return collected_meta, collected_payload


def _collection_summary(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = Counter()
    total_size = 0
    for item in artifacts:
        by_type[str(item.get("doc_type", "unknown"))] += 1
        total_size += int(item.get("size_bytes", 0) or 0)
    return {
        "artifact_count": len(artifacts),
        "total_size_bytes": total_size,
        "doc_types": dict(by_type),
    }


def _save_bundle(
    *,
    context: dict[str, Any],
    startup_id: str,
    collection_id: str,
    window_from: str,
    window_to: str,
    artifacts: list[dict[str, Any]],
    payload_artifacts: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any]]:
    workdir = resolve_workdir(context)
    vault_root = resolve_vault_root(workdir)
    now = _now_utc()
    target_dir = vault_root / startup_id / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)

    bundle_payload = {
        "collection_id": collection_id,
        "startup_id": startup_id,
        "window_from": window_from,
        "window_to": window_to,
        "created_at": now.isoformat(),
        "artifacts": payload_artifacts,
    }
    plaintext = _json_bytes(bundle_payload)
    crypto_store = get_crypto_store(context)
    envelope = crypto_store.encrypt_for_startup(startup_id, plaintext, aad=collection_id.encode("utf-8"))

    bin_path = target_dir / f"{collection_id}.bin"
    meta_path = target_dir / f"{collection_id}.json"
    bin_path.write_bytes(_json_bytes(envelope))

    summary = _collection_summary(artifacts)
    meta_doc = {
        "collection_id": collection_id,
        "startup_id": startup_id,
        "window_from": window_from,
        "window_to": window_to,
        "summary": summary,
        "envelope_meta": {
            "alg": envelope.get("alg"),
            "key_version": envelope.get("key_version"),
            "created_at": envelope.get("created_at"),
        },
        "artifacts": artifacts,
    }
    meta_path.write_text(json.dumps(meta_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(bin_path.relative_to(workdir)), str(meta_path.relative_to(workdir)), summary


def _verify_collection_integrity(
    *,
    context: dict[str, Any],
    startup_id: str,
    collection_id: str,
    encrypted_path: str,
    metadata_path: str,
    expected_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    workdir = resolve_workdir(context)
    store = get_store(context)
    crypto_store = get_crypto_store(context)
    checks: list[dict[str, Any]] = []
    try:
        enc_file = (workdir / encrypted_path).resolve()
        meta_file = (workdir / metadata_path).resolve()
        try:
            enc_file.relative_to(workdir)
            meta_file.relative_to(workdir)
        except ValueError as exc:
            raise RuntimeError("verification path escaped workdir") from exc

        checks.append({"name": "encrypted_file_exists", "ok": enc_file.exists()})
        checks.append({"name": "metadata_file_exists", "ok": meta_file.exists()})
        if not enc_file.exists() or not meta_file.exists():
            raise RuntimeError("missing encrypted/metadata file")

        meta_doc = json.loads(meta_file.read_text(encoding="utf-8"))
        if not isinstance(meta_doc, dict):
            raise RuntimeError("metadata file is not JSON object")

        summary = meta_doc.get("summary", {})
        meta_artifact_count = int(summary.get("artifact_count", 0) or 0) if isinstance(summary, dict) else 0
        checks.append(
            {
                "name": "metadata_artifact_count_matches",
                "ok": meta_artifact_count == len(expected_artifacts),
                "expected": len(expected_artifacts),
                "actual": meta_artifact_count,
            }
        )

        envelope = json.loads(enc_file.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict):
            raise RuntimeError("encrypted file payload is not JSON object")
        plaintext = crypto_store.decrypt_for_startup(
            startup_id,
            envelope,
            aad=collection_id.encode("utf-8"),
        )
        bundle_payload = json.loads(plaintext.decode("utf-8"))
        if not isinstance(bundle_payload, dict):
            raise RuntimeError("decrypted bundle payload is not JSON object")
        bundle_artifacts = bundle_payload.get("artifacts", [])
        if not isinstance(bundle_artifacts, list):
            raise RuntimeError("decrypted bundle artifacts is not list")
        checks.append(
            {
                "name": "decrypted_bundle_artifact_count_matches",
                "ok": len(bundle_artifacts) == len(expected_artifacts),
                "expected": len(expected_artifacts),
                "actual": len(bundle_artifacts),
            }
        )

        expected_sha = {str(item.get("sha256", "")) for item in expected_artifacts if str(item.get("sha256", ""))}
        bundle_sha = {str(item.get("sha256", "")) for item in bundle_artifacts if str(item.get("sha256", ""))}
        checks.append(
            {
                "name": "decrypted_bundle_sha_set_matches",
                "ok": bundle_sha == expected_sha,
                "expected_count": len(expected_sha),
                "actual_count": len(bundle_sha),
            }
        )

        db_artifacts = store.list_artifacts(collection_id=collection_id)
        checks.append(
            {
                "name": "db_artifact_count_matches",
                "ok": len(db_artifacts) == len(expected_artifacts),
                "expected": len(expected_artifacts),
                "actual": len(db_artifacts),
            }
        )
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "checks": checks,
        }

    ok = all(bool(item.get("ok", False)) for item in checks)
    return {"success": ok, "checks": checks}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action", "")).strip().lower()
    startup_id = str(input_data.get("startup_id", "")).strip().lower()
    if not action:
        return {"success": False, "error": "action is required"}
    if not startup_id:
        return {"success": False, "error": "startup_id is required"}

    registry = get_registry(context)
    store = get_store(context)

    if action == "register":
        display_name = str(input_data.get("display_name", startup_id)).strip() or startup_id
        row = registry.register(startup_id, display_name)
        return {"success": True, "action": action, "tenant": row}

    if action == "bind_folder":
        gateway_url = str(input_data.get("gateway_url", "")).strip()
        folder_alias = str(input_data.get("folder_alias", "")).strip() or "desktop_common"
        gateway_secret = str(input_data.get("gateway_secret", "")).strip()
        if not gateway_url:
            return {"success": False, "error": "gateway_url is required"}
        row = registry.bind_folder(
            startup_id,
            gateway_url,
            folder_alias,
            gateway_secret=gateway_secret,
        )
        return {"success": True, "action": action, "tenant": row}

    if action == "status":
        tenant = registry.get(startup_id)
        if tenant is None:
            return {"success": False, "error": f"tenant not found: {startup_id}"}
        pending = store.list_pending_approvals(startup_id=startup_id, limit=20)
        recent = store.list_collections(startup_id=startup_id, limit=5)
        scope_policy = registry.get_scope_policy(startup_id)
        return {
            "success": True,
            "action": action,
            "tenant": tenant,
            "scope_policy": scope_policy,
            "pending_approvals": pending,
            "recent_collections": recent,
        }

    if action != "collect":
        return {"success": False, "error": f"unsupported action: {action}"}

    tenant = registry.get(startup_id)
    if tenant is None:
        return {"success": False, "error": f"tenant not found: {startup_id}"}
    if not bool(tenant.get("active", True)):
        return {"success": False, "error": f"tenant is inactive: {startup_id}"}

    period = str(input_data.get("period", "7d")).strip().lower() or "7d"
    window_from = str(input_data.get("window_from", "")).strip()
    window_to = str(input_data.get("window_to", "")).strip()
    if not window_from or not window_to:
        window_from, window_to = _default_window(period)
    include_ocr = bool(input_data.get("include_ocr", True))
    max_artifacts = int(input_data.get("max_artifacts", 200) or 200)
    max_artifacts = max(1, min(max_artifacts, 1000))
    auto_verify = bool(input_data.get("auto_verify", True))

    request_id = str(uuid4())
    collection_id = str(uuid4())
    artifacts_meta_raw, artifacts_payload_raw = _collect_from_gateway(
        tenant=tenant,
        startup_id=startup_id,
        request_id=request_id,
        window_from=window_from,
        window_to=window_to,
        include_ocr=include_ocr,
        max_artifacts=max_artifacts,
    )
    artifacts_meta, artifacts_payload, scope_audits, policy_summary = filter_artifacts_by_policy(
        tenant=tenant,
        artifacts_meta=artifacts_meta_raw,
        artifacts_payload=artifacts_payload_raw,
    )
    encrypted_path, metadata_path, summary = _save_bundle(
        context=context,
        startup_id=startup_id,
        collection_id=collection_id,
        window_from=window_from,
        window_to=window_to,
        artifacts=artifacts_meta,
        payload_artifacts=artifacts_payload,
    )

    store.create_collection(
        collection_id=collection_id,
        startup_id=startup_id,
        window_from=window_from,
        window_to=window_to,
        status="collected",
        encrypted_path=encrypted_path,
        summary=summary,
    )

    for audit in scope_audits:
        if not isinstance(audit, dict):
            continue
        store.add_scope_audit(
            collection_id=collection_id,
            startup_id=startup_id,
            rel_path=str(audit.get("rel_path", "")),
            doc_type=str(audit.get("doc_type", "unknown")),
            decision=str(audit.get("decision", "reject")),
            reason=str(audit.get("reason", "")),
        )

    for item in artifacts_meta:
        store.add_artifact(
            artifact_id=str(item.get("artifact_id", "")),
            collection_id=collection_id,
            rel_path=str(item.get("rel_path", "")),
            sha256=str(item.get("sha256", "")),
            size_bytes=int(item.get("size_bytes", 0) or 0),
            doc_type=str(item.get("doc_type", "unknown")),
            confidence=float(item.get("confidence", 0.0) or 0.0),
            mtime=str(item.get("mtime", "")),
        )

    normalized_rows = normalize_collection_artifacts(
        startup_id=startup_id,
        collection_id=collection_id,
        artifacts_meta=artifacts_meta,
        artifacts_payload=artifacts_payload,
    )
    for row in normalized_rows:
        store.add_normalized_record(
            record_id=str(row.get("record_id", "")),
            startup_id=startup_id,
            collection_id=collection_id,
            artifact_id=str(row.get("artifact_id", "")),
            schema_type=str(row.get("schema_type", "unknown")),
            payload=row.get("payload", {}) if isinstance(row.get("payload"), dict) else {},
        )

    verification: dict[str, Any] = {"success": True, "checks": []}
    if auto_verify:
        verification = _verify_collection_integrity(
            context=context,
            startup_id=startup_id,
            collection_id=collection_id,
            encrypted_path=encrypted_path,
            metadata_path=metadata_path,
            expected_artifacts=artifacts_meta,
        )
        if not bool(verification.get("success", False)):
            store.set_collection_status(collection_id, "verification_failed")
            return {
                "success": False,
                "action": action,
                "startup_id": startup_id,
                "request_id": request_id,
                "collection_id": collection_id,
                "window_from": window_from,
                "window_to": window_to,
                "encrypted_path": encrypted_path,
                "metadata_path": metadata_path,
                "summary": summary,
                "verification": verification,
                "error": "automatic verification failed",
            }

    risk = assess_collection_risk(
        tenant=tenant,
        artifacts_meta=artifacts_meta,
        scope_audits=scope_audits,
    )
    approval_id = str(uuid4())
    store.create_approval(
        approval_id=approval_id,
        collection_id=collection_id,
        action_type="dispatch_email",
        payload={
            "startup_id": startup_id,
            "collection_id": collection_id,
            "email_recipients": tenant.get("email_recipients", []),
            "metadata_path": metadata_path,
        },
        status="pending",
        risk_score=float(risk.get("score", 0.0) or 0.0),
        risk_level=str(risk.get("level", "low") or "low"),
        risk_reasons=list(risk.get("reasons", [])) if isinstance(risk.get("reasons"), list) else [],
    )
    store.set_collection_status(collection_id, "awaiting_approval")

    return {
        "success": True,
        "action": action,
        "startup_id": startup_id,
        "request_id": request_id,
        "collection_id": collection_id,
        "approval_id": approval_id,
        "window_from": window_from,
        "window_to": window_to,
        "encrypted_path": encrypted_path,
        "metadata_path": metadata_path,
        "summary": summary,
        "verification": verification,
        "scope_policy_summary": policy_summary,
        "normalized_record_count": len(normalized_rows),
        "risk": risk,
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_collect_bundle cli")
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
