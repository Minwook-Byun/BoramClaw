from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from vc_gateway_agent import GatewayConfig, GatewayHandler, GatewayState
from vc_platform.service import build_signed_headers


class TestVCGatewaySecurity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.common_dir = self.root / "common"
        self.common_dir.mkdir(parents=True, exist_ok=True)
        (self.common_dir / "invoice_2026.txt").write_text("세금계산서 invoice", encoding="utf-8")

        config = GatewayConfig(
            startup_id="acme",
            folders={"desktop_common": self.common_dir.resolve()},
            shared_secret="secret-123",
            max_artifacts=200,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        self.server.state = GatewayState(config)  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def _post(self, path: str, payload: dict, *, signed: bool) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if signed:
            headers.update(build_signed_headers("secret-123", body))
        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            exc.close()
            return exc.code, json.loads(raw)

    def test_manifest_invalid_signature(self) -> None:
        status, payload = self._post(
            "/manifest",
            {
                "startup_id": "acme",
                "request_id": "req-1",
                "window_from": "2026-02-01T00:00:00+00:00",
                "window_to": "2026-02-20T00:00:00+00:00",
                "doc_types": ["tax_invoice"],
            },
            signed=False,
        )
        self.assertEqual(status, 401)
        self.assertFalse(payload.get("ok", True))

    def test_artifact_path_traversal_blocked(self) -> None:
        status, payload = self._post(
            "/artifact-content",
            {
                "startup_id": "acme",
                "rel_path": "desktop_common/../../etc/passwd",
            },
            signed=True,
        )
        self.assertIn(status, {400, 403})
        self.assertFalse(payload.get("ok", True))

    def test_symlink_access_blocked(self) -> None:
        target = self.common_dir / "invoice_2026.txt"
        symlink = self.common_dir / "link_invoice.txt"
        try:
            symlink.symlink_to(target)
        except OSError:
            self.skipTest("symlink is not supported in this environment")

        status, payload = self._post(
            "/artifact-content",
            {
                "startup_id": "acme",
                "rel_path": "desktop_common/link_invoice.txt",
            },
            signed=True,
        )
        self.assertEqual(status, 403)
        self.assertFalse(payload.get("ok", True))


if __name__ == "__main__":
    unittest.main()
