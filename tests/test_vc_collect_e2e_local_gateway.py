from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from vc_collect_bundle import run as collect_run
from vc_approval_queue import run as approval_run
from vc_gateway_agent import GatewayConfig, GatewayHandler, GatewayState
from vc_platform.crypto_store import AESGCM
from vc_platform.service import get_store


@unittest.skipIf(AESGCM is None, "cryptography is not installed")
class TestVCCollectE2ELocalGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.startup_common = self.root / "startup" / "common"
        self.startup_common.mkdir(parents=True, exist_ok=True)
        (self.startup_common / "acme_tax_invoice_2026.txt").write_text("세금계산서 #1", encoding="utf-8")
        (self.startup_common / "acme_ir_deck.txt").write_text("investor deck", encoding="utf-8")

        gateway_config = GatewayConfig(
            startup_id="acme",
            folders={"desktop_common": self.startup_common.resolve()},
            shared_secret="local-secret",
            max_artifacts=100,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        self.server.state = GatewayState(gateway_config)  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.gateway_url = f"http://127.0.0.1:{self.server.server_address[1]}"

        self.workdir = self.root / "central"
        (self.workdir / "config").mkdir(parents=True, exist_ok=True)
        (self.workdir / "data").mkdir(parents=True, exist_ok=True)
        (self.workdir / "vault").mkdir(parents=True, exist_ok=True)
        tenants = {
            "tenants": [
                {
                    "startup_id": "acme",
                    "display_name": "Acme AI",
                    "gateway_url": self.gateway_url,
                    "folder_alias": "desktop_common",
                    "gateway_secret": "local-secret",
                    "allowed_doc_types": [
                        "business_registration",
                        "ir_deck",
                        "tax_invoice",
                        "social_insurance",
                        "investment_decision",
                        "unknown",
                    ],
                    "email_recipients": ["ops@vc.test"],
                    "active": True,
                }
            ]
        }
        (self.workdir / "config" / "vc_tenants.json").write_text(
            json.dumps(tenants, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.context = {"workdir": str(self.workdir)}

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def test_collect_then_approve(self) -> None:
        collected = collect_run(
            {"action": "collect", "startup_id": "acme", "period": "7d", "include_ocr": True},
            self.context,
        )
        self.assertTrue(collected.get("success"), msg=str(collected))
        verification = collected.get("verification", {})
        self.assertTrue(isinstance(verification, dict))
        self.assertTrue(verification.get("success"), msg=str(verification))
        risk = collected.get("risk", {})
        self.assertTrue(isinstance(risk, dict))
        self.assertIn("level", risk)
        self.assertGreaterEqual(int(collected.get("normalized_record_count", 0) or 0), 1)
        scope_policy_summary = collected.get("scope_policy_summary", {})
        self.assertTrue(isinstance(scope_policy_summary, dict))
        self.assertGreaterEqual(int(scope_policy_summary.get("allow_count", 0) or 0), 1)
        collection_id = str(collected.get("collection_id", ""))
        approval_id = str(collected.get("approval_id", ""))
        self.assertTrue(collection_id)
        self.assertTrue(approval_id)

        encrypted_path = self.workdir / str(collected.get("encrypted_path", ""))
        metadata_path = self.workdir / str(collected.get("metadata_path", ""))
        self.assertTrue(encrypted_path.exists())
        self.assertTrue(metadata_path.exists())

        store = get_store(self.context)
        pending = store.list_pending_approvals(startup_id="acme")
        self.assertEqual(len(pending), 1)
        normalized = store.list_normalized_records(collection_id=collection_id, limit=100)
        self.assertGreaterEqual(len(normalized), 1)
        scope_audits = store.list_scope_audits(startup_id="acme", collection_id=collection_id, limit=100)
        self.assertGreaterEqual(len(scope_audits), 1)

        approved = approval_run(
            {
                "action": "approve",
                "approval_id": approval_id,
                "approver": "tester",
                "auto_dispatch": True,
                "dry_run_dispatch": True,
            },
            self.context,
        )
        self.assertTrue(approved.get("success"))
        approval = approved.get("approval", {})
        self.assertEqual(approval.get("status"), "approved")


if __name__ == "__main__":
    unittest.main()
