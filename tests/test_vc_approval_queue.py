from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from vc_approval_queue import run as approval_run
from vc_dispatch_email import run as dispatch_run
from vc_platform.service import get_registry, get_store


class TestVCApprovalQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmpdir.name)
        (self.workdir / "config").mkdir(parents=True, exist_ok=True)
        (self.workdir / "data").mkdir(parents=True, exist_ok=True)
        (self.workdir / "vault").mkdir(parents=True, exist_ok=True)
        self.context = {"workdir": str(self.workdir)}

        registry = get_registry(self.context)
        registry.register("acme", "Acme AI")
        registry.bind_folder("acme", "http://127.0.0.1:8742", "desktop_common")
        registry.set_email_recipients("acme", ["ops@vc.test"])

        store = get_store(self.context)
        store.create_collection(
            collection_id="col-1",
            startup_id="acme",
            window_from="2026-02-10T00:00:00+00:00",
            window_to="2026-02-17T00:00:00+00:00",
            status="awaiting_approval",
            encrypted_path="vault/acme/2026/02/17/col-1.bin",
            summary={"artifact_count": 1, "total_size_bytes": 10, "doc_types": {"tax_invoice": 1}},
        )
        store.create_approval(
            approval_id="ap-1",
            collection_id="col-1",
            action_type="dispatch_email",
            payload={
                "startup_id": "acme",
                "collection_id": "col-1",
                "email_recipients": ["ops@vc.test"],
                "metadata_path": "vault/acme/2026/02/17/col-1.json",
            },
            status="pending",
        )
        store.create_approval(
            approval_id="ap-high",
            collection_id="col-1",
            action_type="dispatch_email",
            payload={
                "startup_id": "acme",
                "collection_id": "col-1",
                "email_recipients": ["ops@vc.test"],
                "metadata_path": "vault/acme/2026/02/17/col-1.json",
            },
            status="pending",
            risk_score=0.91,
            risk_level="high",
            risk_reasons=["missing_core_docs:tax_invoice"],
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_pending_and_reject(self) -> None:
        pending = approval_run({"action": "pending", "startup_id": "acme"}, self.context)
        self.assertTrue(pending.get("success"))
        self.assertEqual(pending.get("count"), 2)
        risk_breakdown = pending.get("risk_breakdown", {})
        self.assertEqual(int(risk_breakdown.get("high", 0) or 0), 1)

        rejected = approval_run({"action": "reject", "approval_id": "ap-1", "reason": "invalid"}, self.context)
        self.assertTrue(rejected.get("success"))
        approval = rejected.get("approval", {})
        self.assertEqual(approval.get("status"), "rejected")

    def test_approve_then_dispatch_dry_run(self) -> None:
        blocked = approval_run(
            {
                "action": "approve",
                "approval_id": "ap-high",
                "approver": "tester",
                "auto_dispatch": False,
            },
            self.context,
        )
        self.assertFalse(blocked.get("success"))
        self.assertIn("high-risk", str(blocked.get("error", "")).lower())

        first_signoff = approval_run(
            {
                "action": "approve",
                "approval_id": "ap-high",
                "approver": "alice",
                "auto_dispatch": False,
                "force_high_risk": True,
            },
            self.context,
        )
        self.assertTrue(first_signoff.get("success"))
        self.assertTrue(bool(first_signoff.get("requires_second_approval", False)))
        self.assertEqual(int(first_signoff.get("signoff_count", 0) or 0), 1)

        second_signoff = approval_run(
            {
                "action": "approve",
                "approval_id": "ap-high",
                "approver": "bob",
                "auto_dispatch": False,
                "force_high_risk": True,
            },
            self.context,
        )
        self.assertTrue(second_signoff.get("success"))
        second_approval = second_signoff.get("approval", {})
        self.assertEqual(second_approval.get("status"), "approved")
        signoffs = second_signoff.get("signoffs", [])
        self.assertEqual(len(signoffs), 2)

        approved = approval_run(
            {
                "action": "approve",
                "approval_id": "ap-1",
                "approver": "tester",
                "auto_dispatch": False,
            },
            self.context,
        )
        self.assertTrue(approved.get("success"))
        approval = approved.get("approval", {})
        self.assertEqual(approval.get("status"), "approved")

        dispatched = dispatch_run({"approval_id": "ap-1", "dry_run": True}, self.context)
        self.assertTrue(dispatched.get("success"))
        self.assertFalse(dispatched.get("sent", True))


if __name__ == "__main__":
    unittest.main()
