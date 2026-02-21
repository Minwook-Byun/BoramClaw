from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import time
from typing import Any
import urllib.request

from .crypto_store import VCCryptoStore
from .storage import VCPlatformStore
from .tenant_registry import VCTenantRegistry


def resolve_workdir(context: dict[str, Any]) -> Path:
    raw = str(context.get("workdir", ".")).strip() or "."
    return Path(raw).resolve()


def resolve_registry_path(workdir: Path) -> Path:
    return workdir / "config" / "vc_tenants.json"


def resolve_db_path(workdir: Path) -> Path:
    return workdir / "data" / "vc_platform.db"


def resolve_key_path(workdir: Path) -> Path:
    return workdir / "data" / "vc_keys.json"


def resolve_vault_root(workdir: Path) -> Path:
    return workdir / "vault"


def get_registry(context: dict[str, Any]) -> VCTenantRegistry:
    return VCTenantRegistry(resolve_registry_path(resolve_workdir(context)))


def get_store(context: dict[str, Any]) -> VCPlatformStore:
    return VCPlatformStore(resolve_db_path(resolve_workdir(context)))


def get_crypto_store(context: dict[str, Any]) -> VCCryptoStore:
    return VCCryptoStore(resolve_key_path(resolve_workdir(context)))


def period_to_days(period: str) -> int:
    normalized = period.strip().lower()
    if normalized in {"today", "1d"}:
        return 1
    if normalized in {"7d", "week", "weekly"}:
        return 7
    if normalized in {"30d", "month"}:
        return 30
    if normalized.endswith("d"):
        try:
            days = int(normalized[:-1])
        except ValueError:
            return 7
        return max(1, min(days, 365))
    return 7


def parse_range_mode(mode: str) -> tuple[str | None, str | None]:
    normalized = mode.strip().lower()
    if not normalized.startswith("range:"):
        return None, None
    payload = normalized[len("range:") :]
    parts = [item.strip() for item in payload.split(",")]
    if len(parts) != 2:
        return None, None
    start_raw, end_raw = parts
    if not start_raw or not end_raw:
        return None, None
    return f"{start_raw}T00:00:00+00:00", f"{end_raw}T23:59:59+00:00"


def _sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_signed_headers(secret: str, body: bytes) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    secret_norm = secret.strip()
    if not secret_norm:
        return headers
    ts = str(int(time.time()))
    headers["X-VC-Timestamp"] = ts
    headers["X-VC-Signature"] = _sign_payload(secret_norm, ts, body)
    return headers


def request_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    body = b""
    req_headers = {"Content-Type": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(
        url=url,
        data=(body if method.upper() != "GET" else None),
        headers=req_headers,
        method=method.upper(),
    )
    with urllib.request.urlopen(request, timeout=max(1, timeout)) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"invalid JSON response from {url}")
    return parsed
