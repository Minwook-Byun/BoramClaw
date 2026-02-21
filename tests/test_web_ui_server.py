from __future__ import annotations

import json
import urllib.request
import unittest

from web_ui_server import start_web_ui_server


class TestWebUIServer(unittest.TestCase):
    def test_web_ui_ask_endpoint(self) -> None:
        server = start_web_ui_server(lambda msg: f"echo:{msg}", port=0)
        try:
            url = f"http://127.0.0.1:{server.port}/api/ask"
            body = json.dumps({"message": "안녕"}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("answer"), "echo:안녕")
        finally:
            server.stop()

    def test_web_ui_oauth_callback_endpoint(self) -> None:
        captured: dict[str, str] = {}

        def oauth_callback(query: dict[str, str]) -> dict[str, object]:
            captured.update(query)
            return {"ok": True, "message": "교환 완료"}

        server = start_web_ui_server(lambda msg: f"echo:{msg}", port=0, oauth_callback=oauth_callback)
        try:
            url = f"http://127.0.0.1:{server.port}/oauth/google/callback?code=auth-code&state=conn-123"
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            self.assertIn("OAuth 연결 완료", body)
            self.assertIn("교환 완료", body)
            self.assertEqual(captured.get("code"), "auth-code")
            self.assertEqual(captured.get("state"), "conn-123")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
