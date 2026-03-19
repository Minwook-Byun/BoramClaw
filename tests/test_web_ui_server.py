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

    def test_web_ui_index_contains_advanced_actions(self) -> None:
        server = start_web_ui_server(lambda msg: f"echo:{msg}", port=0)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as resp:
                html = resp.read().decode("utf-8")
            self.assertIn("/advanced", html)
            self.assertIn("/review engineering", html)
            self.assertIn("/review pm", html)
            self.assertIn("/review cpo", html)
            self.assertIn("/wrapup", html)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
