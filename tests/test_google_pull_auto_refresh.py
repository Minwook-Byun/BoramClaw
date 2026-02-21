from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.google_drive_pull import run as drive_pull_run
from tools.google_gmail_pull import run as gmail_pull_run
from tools.google_oauth_connect import run as oauth_connect_run
from vc_platform.google_client import OAuthTokenExchangeResult


class TestGooglePullAutoRefresh(unittest.TestCase):
    def _setup_connected_connection(self, context: dict[str, str]) -> str:
        created = oauth_connect_run(
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
        if not connection_id:
            raise AssertionError("connection_id is required for test setup")
        with patch(
            "tools.google_oauth_connect.GoogleOAuthClient.exchange_code",
            return_value=OAuthTokenExchangeResult(
                access_token="access-token",
                refresh_token="refresh-token",
                token_type="Bearer",
                expires_in=120,
                scope="https://www.googleapis.com/auth/drive.readonly",
                raw_payload={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "token_type": "Bearer",
                    "expires_in": 120,
                    "scope": "https://www.googleapis.com/auth/drive.readonly",
                },
            ),
        ):
            exchanged = oauth_connect_run(
                {
                    "action": "exchange_code",
                    "connection_id": connection_id,
                    "code": "auth-code",
                },
                context,
            )
        if not bool(exchanged.get("success", False)):
            raise AssertionError(f"exchange setup failed: {exchanged}")
        return connection_id

    def test_pull_requires_connected_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "config").mkdir(parents=True, exist_ok=True)
            (workdir / "data").mkdir(parents=True, exist_ok=True)
            context = {"workdir": str(workdir)}

            created = oauth_connect_run(
                {
                    "action": "connect",
                    "startup_id": "acme",
                    "provider": "google_drive",
                    "client_id": "client-id-123",
                    "client_secret": "client-secret-456",
                },
                context,
            )
            connection_id = str(created.get("connection_id", ""))
            result = drive_pull_run(
                {"startup_id": "acme", "connection_id": connection_id, "auto_refresh": False, "dry_run": True},
                context,
            )
            self.assertFalse(result.get("success"))
            self.assertIn("must be connected", str(result.get("error", "")))

    def test_pull_auto_refresh_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "config").mkdir(parents=True, exist_ok=True)
            (workdir / "data").mkdir(parents=True, exist_ok=True)
            context = {"workdir": str(workdir)}
            connection_id = self._setup_connected_connection(context)

            with patch(
                "tools.google_oauth_connect.run",
                return_value={"success": True, "status": "connected", "refreshed": True},
            ):
                drive_res = drive_pull_run(
                    {"startup_id": "acme", "connection_id": connection_id, "auto_refresh": True, "dry_run": True},
                    context,
                )
                gmail_res = gmail_pull_run(
                    {"startup_id": "acme", "connection_id": connection_id, "auto_refresh": True, "dry_run": True},
                    context,
                )

            self.assertTrue(drive_res.get("success"))
            self.assertTrue(gmail_res.get("success"))
            self.assertTrue(bool(drive_res.get("summary", {}).get("refreshed")))
            self.assertTrue(bool(gmail_res.get("summary", {}).get("refreshed")))


if __name__ == "__main__":
    unittest.main()
