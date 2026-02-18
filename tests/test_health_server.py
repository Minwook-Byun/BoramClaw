from __future__ import annotations

import json
import urllib.error
import urllib.request
import unittest

from health_server import start_health_server


class TestHealthServer(unittest.TestCase):
    def test_health_endpoint_returns_ok_payload(self) -> None:
        server = start_health_server(port=0, agent_mode="interactive")
        try:
            url = f"http://127.0.0.1:{server.port}/health"
            with urllib.request.urlopen(url, timeout=2) as resp:
                self.assertEqual(resp.status, 200)
                body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body.get("status"), "ok")
            self.assertEqual(body.get("agent_mode"), "interactive")
            self.assertIsInstance(body.get("uptime_seconds"), int)
        finally:
            server.stop()

    def test_unknown_path_returns_404(self) -> None:
        server = start_health_server(port=0, agent_mode="daemon")
        try:
            url = f"http://127.0.0.1:{server.port}/unknown"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(url, timeout=2)
            self.assertEqual(ctx.exception.code, 404)
            ctx.exception.close()
        finally:
            server.stop()
