from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from vc_scope_policy import run as scope_run
from vc_platform.service import get_registry, get_store


class TestVCScopePolicy(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_get_and_set_policy(self) -> None:
        got = scope_run({"action": "get", "startup_id": "acme"}, self.context)
        self.assertTrue(got.get("success"))
        policy = got.get("policy", {})
        self.assertIn("scope_allow_prefixes", policy)

        updated = scope_run(
            {
                "action": "set",
                "startup_id": "acme",
                "allow_prefixes": "desktop_common/IR,desktop_common/Finance",
                "deny_patterns": "*private*,*secret*",
                "allowed_doc_types": "ir_deck,tax_invoice",
                "consent_reference": "PIPA-2026-001",
                "retention_days": 730,
            },
            self.context,
        )
        self.assertTrue(updated.get("success"), msg=str(updated))
        policy2 = updated.get("policy", {})
        self.assertIn("desktop_common/IR/", policy2.get("scope_allow_prefixes", []))
        self.assertIn("*private*", policy2.get("scope_deny_patterns", []))

    def test_audit_list(self) -> None:
        store = get_store(self.context)
        store.add_scope_audit(
            collection_id="col-1",
            startup_id="acme",
            rel_path="desktop_common/IR/deck.pdf",
            doc_type="ir_deck",
            decision="allow",
            reason="in_scope",
        )
        store.add_scope_audit(
            collection_id="col-1",
            startup_id="acme",
            rel_path="desktop_common/private/memo.txt",
            doc_type="unknown",
            decision="reject",
            reason="deny_pattern:*private*",
        )

        audits = scope_run(
            {"action": "audit", "startup_id": "acme", "decision": "reject", "limit": 10},
            self.context,
        )
        self.assertTrue(audits.get("success"))
        self.assertEqual(int(audits.get("count", 0) or 0), 1)


if __name__ == "__main__":
    unittest.main()
