from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from vc_ops_dashboard import run as dashboard_run
from vc_platform.service import get_registry, get_store


class TestVCOpsDashboard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmpdir.name)
        (self.workdir / "config").mkdir(parents=True, exist_ok=True)
        (self.workdir / "data").mkdir(parents=True, exist_ok=True)
        (self.workdir / "vault").mkdir(parents=True, exist_ok=True)
        self.context = {"workdir": str(self.workdir)}

        registry = get_registry(self.context)
        registry.register("acme", "Acme AI")
        store = get_store(self.context)

        store.create_collection(
            collection_id="col-ok",
            startup_id="acme",
            window_from="2026-02-10T00:00:00+00:00",
            window_to="2026-02-19T00:00:00+00:00",
            status="awaiting_approval",
            encrypted_path="vault/acme/2026/02/19/col-ok.bin",
            summary={"artifact_count": 2, "total_size_bytes": 1234, "doc_types": {"tax_invoice": 1, "unknown": 1}},
        )
        store.add_artifact(
            artifact_id="sha256:a",
            collection_id="col-ok",
            rel_path="desktop_common/tax_invoice.txt",
            sha256="a",
            size_bytes=100,
            doc_type="tax_invoice",
            confidence=0.9,
            mtime="2026-02-19T00:00:00+00:00",
        )
        store.add_artifact(
            artifact_id="sha256:b",
            collection_id="col-ok",
            rel_path="desktop_common/unknown.bin",
            sha256="b",
            size_bytes=120,
            doc_type="unknown",
            confidence=0.4,
            mtime="2026-02-19T00:00:00+00:00",
        )
        store.create_approval(
            approval_id="ap-1",
            collection_id="col-ok",
            action_type="dispatch_email",
            payload={"startup_id": "acme", "collection_id": "col-ok", "email_recipients": ["ops@vc.test"]},
            status="pending",
            risk_score=0.8,
            risk_level="high",
            risk_reasons=["unknown_doc_ratio:0.5"],
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_dashboard_metrics(self) -> None:
        result = dashboard_run({"startup_id": "acme", "window": "30d"}, self.context)
        self.assertTrue(result.get("success"), msg=str(result))
        self.assertEqual(int(result.get("tenant_count", 0) or 0), 1)
        self.assertGreaterEqual(int(result.get("collection_total", 0) or 0), 1)
        risk_distribution = result.get("approval_risk_distribution", {})
        self.assertGreaterEqual(int(risk_distribution.get("high", 0) or 0), 1)
        self.assertIn("VC Ops Dashboard", str(result.get("dashboard_markdown", "")))


if __name__ == "__main__":
    unittest.main()
