from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .classifier import DEFAULT_DOC_TYPES


DEFAULT_ALLOWED_DOC_TYPES = [doc for doc in DEFAULT_DOC_TYPES if doc != "unknown"]


def _validate_startup_id(startup_id: str) -> str:
    normalized = startup_id.strip().lower()
    if not normalized:
        raise ValueError("startup_id is required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", normalized):
        raise ValueError("startup_id must match [a-z0-9][a-z0-9_-]{1,63}")
    return normalized


def _normalize_prefixes(prefixes: list[str], folder_alias: str) -> list[str]:
    alias = folder_alias.strip() or "desktop_common"
    normalized: list[str] = []
    for raw in prefixes:
        value = str(raw).strip().replace("\\", "/")
        if not value:
            continue
        if value.startswith("/"):
            value = value[1:]
        if not value.endswith("/"):
            value += "/"
        if "/" not in value:
            value = f"{value}/"
        if not value.startswith(f"{alias}/") and value != f"{alias}/":
            value = f"{alias}/{value}"
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        normalized = [f"{alias}/"]
    return normalized


def _normalize_patterns(patterns: list[str]) -> list[str]:
    result: list[str] = []
    for raw in patterns:
        value = str(raw).strip()
        if not value:
            continue
        if value not in result:
            result.append(value)
    return result


class VCTenantRegistry:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_doc(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"tenants": []}
        try:
            parsed = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {"tenants": []}
        if not isinstance(parsed, dict):
            return {"tenants": []}
        tenants = parsed.get("tenants")
        if not isinstance(tenants, list):
            parsed["tenants"] = []
        return parsed

    def _save_doc(self, doc: dict[str, Any]) -> None:
        self.config_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_tenants(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        doc = self._load_doc()
        result: list[dict[str, Any]] = []
        for row in doc.get("tenants", []):
            if not isinstance(row, dict):
                continue
            if active_only and not bool(row.get("active", True)):
                continue
            result.append(row)
        return result

    def get(self, startup_id: str) -> dict[str, Any] | None:
        target = _validate_startup_id(startup_id)
        for row in self.list_tenants(active_only=False):
            if str(row.get("startup_id", "")).strip().lower() == target:
                return row
        return None

    def register(self, startup_id: str, display_name: str) -> dict[str, Any]:
        sid = _validate_startup_id(startup_id)
        doc = self._load_doc()
        tenants = doc.setdefault("tenants", [])
        if not isinstance(tenants, list):
            tenants = []
            doc["tenants"] = tenants

        for row in tenants:
            if not isinstance(row, dict):
                continue
            if str(row.get("startup_id", "")).strip().lower() == sid:
                row["display_name"] = display_name.strip() or row.get("display_name", sid)
                row["active"] = True
                self._save_doc(doc)
                return row

        created = {
            "startup_id": sid,
            "display_name": display_name.strip() or sid,
            "gateway_url": "",
            "folder_alias": "desktop_common",
            "allowed_doc_types": list(DEFAULT_ALLOWED_DOC_TYPES),
            "scope_allow_prefixes": ["desktop_common/"],
            "scope_deny_patterns": [],
            "consent_reference": "",
            "retention_days": 365,
            "email_recipients": [],
            "active": True,
        }
        tenants.append(created)
        self._save_doc(doc)
        return created

    def bind_folder(
        self,
        startup_id: str,
        gateway_url: str,
        folder_alias: str,
        *,
        gateway_secret: str = "",
    ) -> dict[str, Any]:
        sid = _validate_startup_id(startup_id)
        tenant = self.get(sid)
        if tenant is None:
            tenant = self.register(sid, sid)

        doc = self._load_doc()
        tenants = doc.get("tenants", [])
        if not isinstance(tenants, list):
            raise RuntimeError("invalid tenant config")

        for row in tenants:
            if not isinstance(row, dict):
                continue
            if str(row.get("startup_id", "")).strip().lower() != sid:
                continue
            row["gateway_url"] = gateway_url.strip()
            row["folder_alias"] = folder_alias.strip() or "desktop_common"
            if gateway_secret.strip():
                row["gateway_secret"] = gateway_secret.strip()
            row.setdefault("scope_allow_prefixes", [f"{row['folder_alias']}/"])
            row.setdefault("scope_deny_patterns", [])
            row.setdefault("consent_reference", "")
            row.setdefault("retention_days", 365)
            row["active"] = True
            self._save_doc(doc)
            return row
        raise RuntimeError(f"tenant not found after register: {sid}")

    def set_email_recipients(self, startup_id: str, recipients: list[str]) -> dict[str, Any]:
        sid = _validate_startup_id(startup_id)
        doc = self._load_doc()
        tenants = doc.get("tenants", [])
        if not isinstance(tenants, list):
            raise RuntimeError("invalid tenant config")
        normalized = [item.strip() for item in recipients if item and item.strip()]
        for row in tenants:
            if not isinstance(row, dict):
                continue
            if str(row.get("startup_id", "")).strip().lower() != sid:
                continue
            row["email_recipients"] = normalized
            self._save_doc(doc)
            return row
        raise ValueError(f"startup_id not found: {sid}")

    def update_scope_policy(
        self,
        *,
        startup_id: str,
        allow_prefixes: list[str] | None = None,
        deny_patterns: list[str] | None = None,
        allowed_doc_types: list[str] | None = None,
        consent_reference: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        sid = _validate_startup_id(startup_id)
        doc = self._load_doc()
        tenants = doc.get("tenants", [])
        if not isinstance(tenants, list):
            raise RuntimeError("invalid tenant config")
        for row in tenants:
            if not isinstance(row, dict):
                continue
            if str(row.get("startup_id", "")).strip().lower() != sid:
                continue
            folder_alias = str(row.get("folder_alias", "desktop_common")).strip() or "desktop_common"
            if allow_prefixes is not None:
                row["scope_allow_prefixes"] = _normalize_prefixes(list(allow_prefixes), folder_alias)
            else:
                row.setdefault("scope_allow_prefixes", [f"{folder_alias}/"])
            if deny_patterns is not None:
                row["scope_deny_patterns"] = _normalize_patterns(list(deny_patterns))
            else:
                row.setdefault("scope_deny_patterns", [])
            if allowed_doc_types is not None:
                normalized_doc_types = [str(item).strip() for item in allowed_doc_types if str(item).strip()]
                if normalized_doc_types:
                    row["allowed_doc_types"] = normalized_doc_types
            if consent_reference is not None:
                row["consent_reference"] = str(consent_reference).strip()
            else:
                row.setdefault("consent_reference", "")
            if retention_days is not None:
                row["retention_days"] = max(1, min(int(retention_days), 3650))
            else:
                row.setdefault("retention_days", 365)
            self._save_doc(doc)
            return row
        raise ValueError(f"startup_id not found: {sid}")

    def get_scope_policy(self, startup_id: str) -> dict[str, Any]:
        tenant = self.get(startup_id)
        if tenant is None:
            raise ValueError(f"startup_id not found: {startup_id}")
        folder_alias = str(tenant.get("folder_alias", "desktop_common")).strip() or "desktop_common"
        return {
            "startup_id": str(tenant.get("startup_id", "")),
            "folder_alias": folder_alias,
            "scope_allow_prefixes": _normalize_prefixes(
                list(tenant.get("scope_allow_prefixes", [f"{folder_alias}/"])),
                folder_alias,
            ),
            "scope_deny_patterns": _normalize_patterns(list(tenant.get("scope_deny_patterns", []))),
            "allowed_doc_types": [
                str(item).strip() for item in tenant.get("allowed_doc_types", []) if str(item).strip()
            ],
            "consent_reference": str(tenant.get("consent_reference", "")).strip(),
            "retention_days": int(tenant.get("retention_days", 365) or 365),
        }
