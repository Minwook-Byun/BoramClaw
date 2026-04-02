from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.google_client import DEFAULT_REDIRECT_URI, GoogleOAuthClient, build_token_ref
from vc_platform.service import get_crypto_store, get_store


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "google_oauth_connect",
    "description": "BYO OAuth connection lifecycle (connect/exchange/refresh/status/test/revoke).",
    "version": __version__,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["connect", "exchange_code", "refresh_token", "status", "test", "revoke"]},
            "startup_id": {"type": "string"},
            "provider": {"type": "string", "description": "google_drive|google_gmail|google"},
            "connection_id": {"type": "string"},
            "code": {"type": "string"},
            "client_id": {"type": "string"},
            "client_secret": {"type": "string"},
            "redirect_uri": {"type": "string"},
            "mode": {"type": "string"},
            "force_refresh": {"type": "boolean"},
            "min_valid_seconds": {"type": "integer", "minimum": 0},
            "scopes": {
                "oneOf": [
                    {"type": "string", "description": "comma/space separated scopes"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "reason": {"type": "string"},
        },
        "required": ["action"],
    },
}


DEFAULT_PROVIDER_SCOPES = {
    "google_drive": [
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ],
    "google_gmail": [
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    "google": [
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
}


def _as_scopes(value: Any, provider: str) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        cleaned = value.replace(",", " ")
        items = [item.strip() for item in cleaned.split() if item.strip()]
    else:
        items = []
    if not items:
        return list(DEFAULT_PROVIDER_SCOPES.get(provider, DEFAULT_PROVIDER_SCOPES["google"]))
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _decode_json_bytes(raw: bytes) -> dict[str, Any]:
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("decoded payload must be an object")
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on", "y", "force", "--force"}


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_iso_datetime(raw: str) -> datetime | None:
    candidate = raw.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sanitize_connection_output(connection: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(connection, dict):
        return connection
    sanitized = dict(connection)
    metadata = sanitized.get("metadata_json", {})
    if isinstance(metadata, dict):
        meta = dict(metadata)
        meta.pop("oauth_client_envelope", None)
        meta.pop("oauth_token_envelope", None)
        sanitized["metadata_json"] = meta
    return sanitized


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action", "")).strip().lower()
    if not action:
        return {"success": False, "error": "action is required"}

    store = get_store(context)
    crypto_store = get_crypto_store(context)
    oauth_client = GoogleOAuthClient()

    if action == "connect":
        startup_id = str(input_data.get("startup_id", "")).strip().lower()
        provider = str(input_data.get("provider", "google")).strip().lower() or "google"
        if not startup_id:
            return {"success": False, "error": "startup_id is required"}
        if provider not in {"google_drive", "google_gmail", "google"}:
            return {"success": False, "error": "provider must be google_drive|google_gmail|google"}

        connection_id = str(input_data.get("connection_id", "")).strip() or str(uuid4())
        mode = str(input_data.get("mode", "byo_oauth")).strip() or "byo_oauth"
        client_id = str(input_data.get("client_id", "")).strip() or str(os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")).strip()
        client_secret = (
            str(input_data.get("client_secret", "")).strip()
            or str(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")).strip()
        )
        redirect_uri = str(input_data.get("redirect_uri", "")).strip() or DEFAULT_REDIRECT_URI
        scopes = _as_scopes(input_data.get("scopes"), provider)

        if client_id and client_secret:
            client_config = {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            }
            client_envelope = crypto_store.encrypt_for_startup(
                startup_id,
                _json_bytes(client_config),
                aad=connection_id.encode("utf-8"),
            )
            scaffold = oauth_client.connect_scaffold(
                provider=provider,
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
                state=connection_id,
                redirect_uri=redirect_uri,
                mode=mode,
            )
            status = "pending_consent"
            token_ref = scaffold.token_ref
            metadata = {
                "consent_url": scaffold.consent_url,
                "client_id_masked": scaffold.client_id_masked,
                "redirect_uri": redirect_uri,
                "oauth_client_envelope": client_envelope,
                "notes": scaffold.notes,
            }
            next_steps = [
                "브라우저에서 consent_url로 접속해 사용자 동의를 받으세요.",
                "동의 후 redirect_uri 콜백에서 code/state가 수신되면 exchange_code가 자동/수동으로 실행됩니다.",
            ]
        else:
            status = "awaiting_credentials"
            token_ref = ""
            metadata = {
                "redirect_uri": redirect_uri,
                "notes": "client_id/client_secret이 없어 연결을 생성만 했습니다.",
            }
            next_steps = [
                "client_id/client_secret을 입력한 뒤 connect를 다시 실행하세요.",
                "또는 환경변수 GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET을 설정하세요.",
            ]

        store.upsert_integration_connection(
            connection_id=connection_id,
            startup_id=startup_id,
            provider=provider,
            mode=mode,
            status=status,
            scopes=scopes,
            token_ref=token_ref,
            refresh_token_ref="",
            metadata=metadata,
        )
        connection = store.get_integration_connection(connection_id)
        return {
            "success": True,
            "action": action,
            "connection_id": connection_id,
            "status": status,
            "connection": connection,
            "next_steps": next_steps,
        }

    if action == "exchange_code":
        connection_id = str(input_data.get("connection_id", "")).strip()
        code = str(input_data.get("code", "")).strip()
        if not connection_id:
            return {"success": False, "error": "connection_id is required"}
        if not code:
            return {"success": False, "error": "code is required"}

        connection = store.get_integration_connection(connection_id)
        if connection is None:
            return {"success": False, "error": f"connection_id not found: {connection_id}"}

        startup_id = str(connection.get("startup_id", "")).strip().lower()
        provider = str(connection.get("provider", "")).strip().lower()
        mode = str(connection.get("mode", "byo_oauth")).strip() or "byo_oauth"
        scopes = connection.get("scopes_json", [])
        if not isinstance(scopes, list):
            scopes = []
        metadata = connection.get("metadata_json", {})
        if not isinstance(metadata, dict):
            metadata = {}

        redirect_uri = str(input_data.get("redirect_uri", "")).strip() or str(metadata.get("redirect_uri", "")).strip()
        redirect_uri = redirect_uri or DEFAULT_REDIRECT_URI

        client_id = str(input_data.get("client_id", "")).strip() or str(os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")).strip()
        client_secret = (
            str(input_data.get("client_secret", "")).strip()
            or str(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")).strip()
        )
        envelope = metadata.get("oauth_client_envelope")
        if isinstance(envelope, dict):
            try:
                decrypted = crypto_store.decrypt_for_startup(
                    startup_id,
                    envelope,
                    aad=connection_id.encode("utf-8"),
                )
                parsed_config = _decode_json_bytes(decrypted)
                client_id = str(parsed_config.get("client_id", "")).strip() or client_id
                client_secret = str(parsed_config.get("client_secret", "")).strip() or client_secret
                redirect_uri = str(parsed_config.get("redirect_uri", "")).strip() or redirect_uri
            except Exception as exc:
                return {"success": False, "error": f"oauth client config decrypt failed: {exc}"}

        if not client_id or not client_secret:
            return {
                "success": False,
                "error": "client_id/client_secret not available. run connect with credentials first.",
            }

        exchanged = oauth_client.exchange_code(
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
        token_payload = dict(exchanged.raw_payload)
        token_envelope = crypto_store.encrypt_for_startup(
            startup_id,
            _json_bytes(token_payload),
            aad=f"{connection_id}:token".encode("utf-8"),
        )
        connected_at = _now_iso()
        expires_at = ""
        if exchanged.expires_in > 0:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=exchanged.expires_in)).isoformat()

        next_metadata = dict(metadata)
        next_metadata["redirect_uri"] = redirect_uri
        next_metadata["oauth_token_envelope"] = token_envelope
        next_metadata["token_type"] = exchanged.token_type
        next_metadata["scope"] = exchanged.scope
        next_metadata["connected_at"] = connected_at
        next_metadata["token_expires_at"] = expires_at
        next_metadata["last_exchange_at"] = connected_at
        next_metadata["notes"] = "authorization_code exchanged successfully."

        connection_token_ref = build_token_ref(
            provider,
            {"connection_id": connection_id, "connected_at": connected_at, "token_type": exchanged.token_type},
        )
        refresh_token_ref = ""
        if exchanged.refresh_token:
            refresh_token_ref = build_token_ref(
                provider,
                {"connection_id": connection_id, "connected_at": connected_at, "kind": "refresh"},
            )

        store.upsert_integration_connection(
            connection_id=connection_id,
            startup_id=startup_id,
            provider=provider,
            mode=mode,
            status="connected",
            scopes=[str(item).strip() for item in scopes if str(item).strip()],
            token_ref=connection_token_ref,
            refresh_token_ref=refresh_token_ref,
            metadata=next_metadata,
        )
        updated = _sanitize_connection_output(store.get_integration_connection(connection_id))

        return {
            "success": True,
            "action": action,
            "connection_id": connection_id,
            "status": "connected",
            "token_type": exchanged.token_type,
            "expires_in": exchanged.expires_in,
            "scope": exchanged.scope,
            "connection": updated,
        }

    if action == "refresh_token":
        connection_id = str(input_data.get("connection_id", "")).strip()
        if not connection_id:
            return {"success": False, "error": "connection_id is required"}

        force_refresh = _parse_bool(input_data.get("force_refresh"), False)
        min_valid_seconds = max(0, _parse_int(input_data.get("min_valid_seconds", 120), 120))

        connection = store.get_integration_connection(connection_id)
        if connection is None:
            return {"success": False, "error": f"connection_id not found: {connection_id}"}

        startup_id = str(connection.get("startup_id", "")).strip().lower()
        provider = str(connection.get("provider", "")).strip().lower()
        mode = str(connection.get("mode", "byo_oauth")).strip() or "byo_oauth"
        scopes = connection.get("scopes_json", [])
        if not isinstance(scopes, list):
            scopes = []
        metadata = connection.get("metadata_json", {})
        if not isinstance(metadata, dict):
            metadata = {}

        redirect_uri = str(input_data.get("redirect_uri", "")).strip() or str(metadata.get("redirect_uri", "")).strip()
        redirect_uri = redirect_uri or DEFAULT_REDIRECT_URI

        client_id = str(input_data.get("client_id", "")).strip() or str(os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")).strip()
        client_secret = (
            str(input_data.get("client_secret", "")).strip()
            or str(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")).strip()
        )
        client_envelope = metadata.get("oauth_client_envelope")
        if isinstance(client_envelope, dict):
            try:
                decrypted_client = crypto_store.decrypt_for_startup(
                    startup_id,
                    client_envelope,
                    aad=connection_id.encode("utf-8"),
                )
                parsed_client = _decode_json_bytes(decrypted_client)
                client_id = str(parsed_client.get("client_id", "")).strip() or client_id
                client_secret = str(parsed_client.get("client_secret", "")).strip() or client_secret
                redirect_uri = str(parsed_client.get("redirect_uri", "")).strip() or redirect_uri
            except Exception as exc:
                return {"success": False, "error": f"oauth client config decrypt failed: {exc}"}
        if not client_id or not client_secret:
            return {
                "success": False,
                "error": "client_id/client_secret not available. run connect with credentials first.",
            }

        token_payload: dict[str, Any] = {}
        token_envelope = metadata.get("oauth_token_envelope")
        if isinstance(token_envelope, dict):
            try:
                decrypted_token = crypto_store.decrypt_for_startup(
                    startup_id,
                    token_envelope,
                    aad=f"{connection_id}:token".encode("utf-8"),
                )
                token_payload = _decode_json_bytes(decrypted_token)
            except Exception as exc:
                return {"success": False, "error": f"oauth token payload decrypt failed: {exc}"}

        refresh_token = str(token_payload.get("refresh_token", "")).strip()
        if not refresh_token:
            return {
                "success": False,
                "error": "refresh_token is missing. re-run exchange_code with offline consent to obtain refresh token.",
            }

        now = datetime.now(timezone.utc)
        expires_at_dt = _parse_iso_datetime(str(metadata.get("token_expires_at", "")))
        seconds_left = -1
        if expires_at_dt is not None:
            seconds_left = int((expires_at_dt - now).total_seconds())
        if not force_refresh and expires_at_dt is not None and seconds_left > min_valid_seconds:
            return {
                "success": True,
                "action": action,
                "connection_id": connection_id,
                "status": str(connection.get("status", "connected") or "connected"),
                "refreshed": False,
                "seconds_left": seconds_left,
                "min_valid_seconds": min_valid_seconds,
                "connection": _sanitize_connection_output(connection),
            }

        refreshed = oauth_client.refresh_access_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        next_token_payload = dict(token_payload)
        next_token_payload.update(dict(refreshed.raw_payload))
        if not str(next_token_payload.get("refresh_token", "")).strip():
            next_token_payload["refresh_token"] = refresh_token

        refreshed_at = _now_iso()
        expires_at = ""
        if refreshed.expires_in > 0:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=refreshed.expires_in)).isoformat()

        next_token_envelope = crypto_store.encrypt_for_startup(
            startup_id,
            _json_bytes(next_token_payload),
            aad=f"{connection_id}:token".encode("utf-8"),
        )
        next_metadata = dict(metadata)
        next_metadata["redirect_uri"] = redirect_uri
        next_metadata["oauth_token_envelope"] = next_token_envelope
        next_metadata["token_type"] = refreshed.token_type
        next_metadata["scope"] = refreshed.scope
        next_metadata["token_expires_at"] = expires_at
        next_metadata["last_refresh_at"] = refreshed_at
        next_metadata["notes"] = "refresh_token grant exchanged successfully."

        next_token_ref = build_token_ref(
            provider,
            {"connection_id": connection_id, "refreshed_at": refreshed_at, "token_type": refreshed.token_type},
        )
        next_refresh_token = str(next_token_payload.get("refresh_token", "")).strip()
        next_refresh_token_ref = str(connection.get("refresh_token_ref", "")).strip()
        if next_refresh_token:
            next_refresh_token_ref = build_token_ref(
                provider,
                {"connection_id": connection_id, "refreshed_at": refreshed_at, "kind": "refresh"},
            )

        store.upsert_integration_connection(
            connection_id=connection_id,
            startup_id=startup_id,
            provider=provider,
            mode=mode,
            status="connected",
            scopes=[str(item).strip() for item in scopes if str(item).strip()],
            token_ref=next_token_ref,
            refresh_token_ref=next_refresh_token_ref,
            metadata=next_metadata,
        )
        updated = _sanitize_connection_output(store.get_integration_connection(connection_id))
        return {
            "success": True,
            "action": action,
            "connection_id": connection_id,
            "status": "connected",
            "refreshed": True,
            "token_type": refreshed.token_type,
            "expires_in": refreshed.expires_in,
            "scope": refreshed.scope,
            "connection": updated,
        }

    if action == "status":
        startup_id = str(input_data.get("startup_id", "")).strip().lower()
        if not startup_id:
            return {"success": False, "error": "startup_id is required"}
        provider = str(input_data.get("provider", "")).strip().lower() or None
        rows = store.list_integration_connections(startup_id=startup_id, provider=provider, limit=200)
        return {
            "success": True,
            "action": action,
            "startup_id": startup_id,
            "provider": provider,
            "count": len(rows),
            "connections": rows,
        }

    if action == "test":
        connection_id = str(input_data.get("connection_id", "")).strip()
        if not connection_id:
            return {"success": False, "error": "connection_id is required"}
        row = store.get_integration_connection(connection_id)
        if row is None:
            return {"success": False, "error": f"connection_id not found: {connection_id}"}
        status = str(row.get("status", ""))
        auto_refresh = _parse_bool(input_data.get("auto_refresh"), True)
        refresh_result: dict[str, Any] | None = None
        if status == "connected" and auto_refresh:
            refresh_result = run(
                {
                    "action": "refresh_token",
                    "connection_id": connection_id,
                    "min_valid_seconds": _parse_int(input_data.get("min_valid_seconds", 120), 120),
                },
                context,
            )
            if not bool(refresh_result.get("success", False)):
                return {
                    "success": False,
                    "error": str(refresh_result.get("error", "auto refresh failed")).strip() or "auto refresh failed",
                    "connection_id": connection_id,
                }
            status = str(refresh_result.get("status", status))
        is_connectable = status not in {"revoked", "error"}
        return {
            "success": True,
            "action": action,
            "connection_id": connection_id,
            "status": status,
            "is_connectable": is_connectable,
            "auto_refresh": auto_refresh,
            "refresh_result": refresh_result,
        }

    if action == "revoke":
        connection_id = str(input_data.get("connection_id", "")).strip()
        if not connection_id:
            return {"success": False, "error": "connection_id is required"}
        reason = str(input_data.get("reason", "manual revoke")).strip() or "manual revoke"
        row = store.get_integration_connection(connection_id)
        if row is None:
            return {"success": False, "error": f"connection_id not found: {connection_id}"}
        store.set_integration_connection_status(connection_id=connection_id, status="revoked", reason=reason)
        updated = store.get_integration_connection(connection_id)
        return {
            "success": True,
            "action": action,
            "connection_id": connection_id,
            "status": "revoked",
            "connection": updated,
        }

    return {"success": False, "error": f"unsupported action: {action}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="google_oauth_connect cli")
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
