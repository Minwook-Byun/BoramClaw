from __future__ import annotations

import fnmatch
from typing import Any


def _normalize_rel_path(rel_path: str) -> str:
    return rel_path.strip().replace("\\", "/").lstrip("/")


def _normalize_prefix(prefix: str) -> str:
    value = _normalize_rel_path(prefix)
    if value and not value.endswith("/"):
        value += "/"
    return value


def _normalize_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if value and value not in result:
            result.append(value)
    return result


def resolve_scope_policy(tenant: dict[str, Any]) -> dict[str, Any]:
    folder_alias = str(tenant.get("folder_alias", "desktop_common")).strip() or "desktop_common"
    allow_prefixes = _normalize_list(tenant.get("scope_allow_prefixes", [f"{folder_alias}/"]))
    if not allow_prefixes:
        allow_prefixes = [f"{folder_alias}/"]
    allow_prefixes = [_normalize_prefix(prefix) for prefix in allow_prefixes if _normalize_prefix(prefix)]
    if not allow_prefixes:
        allow_prefixes = [f"{folder_alias}/"]

    deny_patterns = _normalize_list(tenant.get("scope_deny_patterns", []))
    allowed_doc_types = _normalize_list(tenant.get("allowed_doc_types", []))
    return {
        "folder_alias": folder_alias,
        "allow_prefixes": allow_prefixes,
        "deny_patterns": deny_patterns,
        "allowed_doc_types": allowed_doc_types,
        "consent_reference": str(tenant.get("consent_reference", "")).strip(),
        "retention_days": int(tenant.get("retention_days", 365) or 365),
    }


def evaluate_artifact_policy(
    *,
    rel_path: str,
    doc_type: str,
    policy: dict[str, Any],
) -> tuple[bool, str]:
    normalized_path = _normalize_rel_path(rel_path)
    if not normalized_path:
        return False, "empty_rel_path"

    allow_prefixes = [str(item).strip() for item in policy.get("allow_prefixes", []) if str(item).strip()]
    if allow_prefixes:
        if not any(normalized_path.startswith(_normalize_prefix(prefix)) for prefix in allow_prefixes):
            return False, "outside_allowed_scope"

    deny_patterns = [str(item).strip() for item in policy.get("deny_patterns", []) if str(item).strip()]
    low = normalized_path.lower()
    for pattern in deny_patterns:
        pat = pattern.lower()
        if fnmatch.fnmatch(low, pat) or pat in low:
            return False, f"deny_pattern:{pattern}"

    allowed_doc_types = [str(item).strip() for item in policy.get("allowed_doc_types", []) if str(item).strip()]
    if allowed_doc_types and doc_type not in allowed_doc_types:
        return False, "doc_type_not_allowed"

    return True, "in_scope"


def filter_artifacts_by_policy(
    *,
    tenant: dict[str, Any],
    artifacts_meta: list[dict[str, Any]],
    artifacts_payload: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    policy = resolve_scope_policy(tenant)
    payload_by_path: dict[str, dict[str, Any]] = {}
    for item in artifacts_payload:
        if not isinstance(item, dict):
            continue
        rel_path = _normalize_rel_path(str(item.get("rel_path", "")))
        if rel_path:
            payload_by_path[rel_path] = item

    accepted_meta: list[dict[str, Any]] = []
    accepted_payload: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for meta in artifacts_meta:
        if not isinstance(meta, dict):
            continue
        rel_path = _normalize_rel_path(str(meta.get("rel_path", "")))
        doc_type = str(meta.get("doc_type", "unknown"))
        allowed, reason = evaluate_artifact_policy(rel_path=rel_path, doc_type=doc_type, policy=policy)
        decision = "allow" if allowed else "reject"
        audits.append(
            {
                "rel_path": rel_path,
                "doc_type": doc_type,
                "decision": decision,
                "reason": reason,
            }
        )
        if not allowed:
            continue
        accepted_meta.append(meta)
        payload_item = payload_by_path.get(rel_path)
        if payload_item is not None:
            accepted_payload.append(payload_item)

    filtered_rel_paths = {_normalize_rel_path(str(item.get("rel_path", ""))) for item in accepted_meta}
    accepted_payload = [item for item in accepted_payload if _normalize_rel_path(str(item.get("rel_path", ""))) in filtered_rel_paths]

    policy_summary = {
        "allow_count": sum(1 for row in audits if row.get("decision") == "allow"),
        "reject_count": sum(1 for row in audits if row.get("decision") == "reject"),
        "policy": policy,
    }
    return accepted_meta, accepted_payload, audits, policy_summary
