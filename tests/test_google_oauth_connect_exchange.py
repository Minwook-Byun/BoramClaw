from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.google_oauth_connect import run
from vc_platform.google_client import OAuthTokenExchangeResult


class TestGoogleOAuthConnectExchange(unittest.TestCase):
    def test_exchange_code_updates_connection_to_connected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "config").mkdir(parents=True, exist_ok=True)
            (workdir / "data").mkdir(parents=True, exist_ok=True)
            context = {"workdir": str(workdir)}

            created = run(
                {
                    "action": "connect",
                    "startup_id": "acme",
                    "provider": "google_drive",
                    "client_id": "client-id-123",
                    "client_secret": "client-secret-456",
                    "redirect_uri": "http://127.0.0.1:8091/oauth/google/callback",
                },
                context,
            )
            self.assertTrue(created.get("success"))
            connection_id = str(created.get("connection_id", ""))
            self.assertTrue(connection_id)

            with patch(
                "tools.google_oauth_connect.GoogleOAuthClient.exchange_code",
                return_value=OAuthTokenExchangeResult(
                    access_token="access-token",
                    refresh_token="refresh-token",
                    token_type="Bearer",
                    expires_in=3600,
                    scope="https://www.googleapis.com/auth/drive.readonly",
                    raw_payload={
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/drive.readonly",
                    },
                ),
            ):
                exchanged = run(
                    {
                        "action": "exchange_code",
                        "connection_id": connection_id,
                        "code": "auth-code-abc",
                    },
                    context,
                )

            self.assertTrue(exchanged.get("success"))
            self.assertEqual(exchanged.get("status"), "connected")
            self.assertEqual(exchanged.get("token_type"), "Bearer")
            self.assertEqual(int(exchanged.get("expires_in", 0) or 0), 3600)

            status = run({"action": "status", "startup_id": "acme"}, context)
            self.assertTrue(status.get("success"))
            connections = status.get("connections", [])
            self.assertIsInstance(connections, list)
            self.assertEqual(len(connections), 1)
            row = connections[0]
            self.assertEqual(row.get("status"), "connected")
            self.assertTrue(str(row.get("token_ref", "")).strip())

    def test_refresh_token_updates_access_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "config").mkdir(parents=True, exist_ok=True)
            (workdir / "data").mkdir(parents=True, exist_ok=True)
            context = {"workdir": str(workdir)}

            created = run(
                {
                    "action": "connect",
                    "startup_id": "acme",
                    "provider": "google_drive",
                    "client_id": "client-id-123",
                    "client_secret": "client-secret-456",
                    "redirect_uri": "http://127.0.0.1:8091/oauth/google/callback",
                },
                context,
            )
            connection_id = str(created.get("connection_id", ""))
            self.assertTrue(connection_id)

            with patch(
                "tools.google_oauth_connect.GoogleOAuthClient.exchange_code",
                return_value=OAuthTokenExchangeResult(
                    access_token="access-token",
                    refresh_token="refresh-token",
                    token_type="Bearer",
                    expires_in=30,
                    scope="https://www.googleapis.com/auth/drive.readonly",
                    raw_payload={
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "token_type": "Bearer",
                        "expires_in": 30,
                        "scope": "https://www.googleapis.com/auth/drive.readonly",
                    },
                ),
            ):
                exchanged = run(
                    {
                        "action": "exchange_code",
                        "connection_id": connection_id,
                        "code": "auth-code-abc",
                    },
                    context,
                )
            self.assertTrue(exchanged.get("success"))

            with patch(
                "tools.google_oauth_connect.GoogleOAuthClient.refresh_access_token",
                return_value=OAuthTokenExchangeResult(
                    access_token="access-token-new",
                    refresh_token="",
                    token_type="Bearer",
                    expires_in=3600,
                    scope="https://www.googleapis.com/auth/drive.readonly",
                    raw_payload={
                        "access_token": "access-token-new",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/drive.readonly",
                    },
                ),
            ):
                refreshed = run(
                    {
                        "action": "refresh_token",
                        "connection_id": connection_id,
                        "force_refresh": True,
                    },
                    context,
                )
            self.assertTrue(refreshed.get("success"))
            self.assertTrue(bool(refreshed.get("refreshed")))
            self.assertEqual(refreshed.get("status"), "connected")


if __name__ == "__main__":
    unittest.main()
