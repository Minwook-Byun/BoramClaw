from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
import urllib.parse
import urllib.request
import urllib.error


DEFAULT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
GOOGLE_OAUTH_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def _scope_csv(scopes: list[str]) -> str:
    ordered: list[str] = []
    for item in scopes:
        value = str(item).strip()
        if not value or value in ordered:
            continue
        ordered.append(value)
    return " ".join(ordered)


def _mask_secret(value: str) -> str:
    text = value.strip()
    if len(text) <= 6:
        return "***"
    return f"{text[:3]}...{text[-3:]}"


def build_token_ref(provider: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{provider}:{digest[:24]}"


@dataclass(frozen=True)
class OAuthConnectResult:
    provider: str
    consent_url: str
    token_ref: str
    client_id_masked: str
    mode: str
    notes: str


@dataclass(frozen=True)
class OAuthTokenExchangeResult:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    scope: str
    raw_payload: dict[str, Any]


class GoogleOAuthClient:
    """Google OAuth helper for consent URL and auth-code exchange."""

    def build_consent_url(
        self,
        *,
        client_id: str,
        scopes: list[str],
        state: str,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
        access_type: str = "offline",
        prompt: str = "consent",
    ) -> str:
        query = {
            "client_id": client_id.strip(),
            "redirect_uri": redirect_uri.strip() or DEFAULT_REDIRECT_URI,
            "response_type": "code",
            "scope": _scope_csv(scopes),
            "state": state.strip(),
            "access_type": access_type,
            "prompt": prompt,
        }
        return f"{GOOGLE_OAUTH_AUTH_BASE}?{urllib.parse.urlencode(query)}"

    def connect_scaffold(
        self,
        *,
        provider: str,
        client_id: str,
        client_secret: str,
        scopes: list[str],
        state: str,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
        mode: str = "byo_oauth",
    ) -> OAuthConnectResult:
        consent_url = self.build_consent_url(
            client_id=client_id,
            scopes=scopes,
            state=state,
            redirect_uri=redirect_uri,
        )
        token_ref = build_token_ref(
            provider,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "scopes": scopes,
                "redirect_uri": redirect_uri,
                "state": state,
                "mode": mode,
            },
        )
        return OAuthConnectResult(
            provider=provider,
            consent_url=consent_url,
            token_ref=token_ref,
            client_id_masked=_mask_secret(client_id),
            mode=mode,
            notes="OAuth consent URL generated.",
        )

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
        endpoint: str = GOOGLE_OAUTH_TOKEN_ENDPOINT,
        timeout: int = 20,
    ) -> OAuthTokenExchangeResult:
        payload = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "code": code.strip(),
            "redirect_uri": redirect_uri.strip() or DEFAULT_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        return self._post_token_request(payload=payload, endpoint=endpoint, timeout=timeout)

    def refresh_access_token(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        endpoint: str = GOOGLE_OAUTH_TOKEN_ENDPOINT,
        timeout: int = 20,
    ) -> OAuthTokenExchangeResult:
        payload = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "refresh_token": refresh_token.strip(),
            "grant_type": "refresh_token",
        }
        return self._post_token_request(payload=payload, endpoint=endpoint, timeout=timeout)

    def _post_token_request(
        self,
        *,
        payload: dict[str, str],
        endpoint: str,
        timeout: int,
    ) -> OAuthTokenExchangeResult:
        body = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            url=endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed_error = json.loads(error_raw)
            except Exception:
                parsed_error = {"raw": error_raw}
            raise RuntimeError(f"google token exchange failed: http={exc.code} payload={parsed_error}") from exc

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("google token exchange failed: invalid JSON payload")
        access_token = str(parsed.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError(f"google token exchange failed: access_token missing ({parsed})")
        refresh_token = str(parsed.get("refresh_token", "")).strip()
        token_type = str(parsed.get("token_type", "")).strip()
        scope = str(parsed.get("scope", "")).strip()
        expires_raw = parsed.get("expires_in", 0)
        try:
            expires_in = int(expires_raw)
        except Exception:
            expires_in = 0
        return OAuthTokenExchangeResult(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            expires_in=max(0, expires_in),
            scope=scope,
            raw_payload=parsed,
        )
