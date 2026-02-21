from __future__ import annotations

import unittest

from runtime_commands import parse_vc_command


class TestVCCommandParser(unittest.TestCase):
    def test_register(self) -> None:
        parsed = parse_vc_command("/vc register acme Acme AI")
        assert parsed is not None
        self.assertEqual(parsed["tool_name"], "vc_collect_bundle")
        self.assertEqual(parsed["tool_input"]["action"], "register")
        self.assertEqual(parsed["tool_input"]["startup_id"], "acme")
        self.assertEqual(parsed["tool_input"]["display_name"], "Acme AI")

    def test_bind_folder(self) -> None:
        parsed = parse_vc_command("/vc bind-folder acme http://127.0.0.1:8742 desktop_common secret123")
        assert parsed is not None
        self.assertEqual(parsed["tool_name"], "vc_collect_bundle")
        self.assertEqual(parsed["tool_input"]["action"], "bind_folder")
        self.assertEqual(parsed["tool_input"]["gateway_secret"], "secret123")

    def test_collect_report_pending(self) -> None:
        parsed_collect = parse_vc_command("/vc collect acme 30d")
        assert parsed_collect is not None
        self.assertEqual(parsed_collect["tool_name"], "vc_collect_bundle")
        self.assertEqual(parsed_collect["tool_input"]["period"], "30d")

        parsed_report = parse_vc_command("/vc report acme weekly")
        assert parsed_report is not None
        self.assertEqual(parsed_report["tool_name"], "vc_generate_report")
        self.assertEqual(parsed_report["tool_input"]["mode"], "weekly")

        parsed_pending = parse_vc_command("/vc pending acme")
        assert parsed_pending is not None
        self.assertEqual(parsed_pending["tool_name"], "vc_approval_queue")
        self.assertEqual(parsed_pending["tool_input"]["startup_id"], "acme")

        parsed_verify = parse_vc_command("/vc verify acme")
        assert parsed_verify is not None
        self.assertEqual(parsed_verify["tool_name"], "vc_remote_e2e_smoke")
        self.assertEqual(parsed_verify["tool_input"]["startup_id"], "acme")

        parsed_onboard = parse_vc_command("/vc onboard acme 7d")
        assert parsed_onboard is not None
        self.assertEqual(parsed_onboard["tool_name"], "vc_onboarding_check")
        self.assertEqual(parsed_onboard["tool_input"]["sample_period"], "7d")

    def test_approve_reject_status(self) -> None:
        approval_id = "11111111-2222-3333-4444-555555555555"
        parsed_approve = parse_vc_command(f"/vc approve {approval_id} force by=alice")
        assert parsed_approve is not None
        self.assertEqual(parsed_approve["tool_name"], "vc_approval_queue")
        self.assertEqual(parsed_approve["tool_input"]["action"], "approve")
        self.assertTrue(parsed_approve["tool_input"]["force_high_risk"])
        self.assertEqual(parsed_approve["tool_input"]["approver"], "alice")

        parsed_reject = parse_vc_command(f"/vc reject {approval_id} data issue")
        assert parsed_reject is not None
        self.assertEqual(parsed_reject["tool_input"]["action"], "reject")
        self.assertEqual(parsed_reject["tool_input"]["reason"], "data issue")

        parsed_status = parse_vc_command("/vc status acme")
        assert parsed_status is not None
        self.assertEqual(parsed_status["tool_name"], "vc_collect_bundle")
        self.assertEqual(parsed_status["tool_input"]["action"], "status")

    def test_scope_and_dashboard_commands(self) -> None:
        parsed_scope_get = parse_vc_command("/vc scope acme")
        assert parsed_scope_get is not None
        self.assertEqual(parsed_scope_get["tool_name"], "vc_scope_policy")
        self.assertEqual(parsed_scope_get["tool_input"]["action"], "get")

        parsed_scope_set = parse_vc_command(
            "/vc scope acme allow=desktop_common/IR,desktop_common/Finance deny=*private* docs=ir_deck,tax_invoice"
        )
        assert parsed_scope_set is not None
        self.assertEqual(parsed_scope_set["tool_name"], "vc_scope_policy")
        self.assertEqual(parsed_scope_set["tool_input"]["action"], "set")
        self.assertIn("allow_prefixes", parsed_scope_set["tool_input"])

        parsed_scope_audit = parse_vc_command("/vc scope-audit acme 50 reject")
        assert parsed_scope_audit is not None
        self.assertEqual(parsed_scope_audit["tool_name"], "vc_scope_policy")
        self.assertEqual(parsed_scope_audit["tool_input"]["action"], "audit")
        self.assertEqual(parsed_scope_audit["tool_input"]["decision"], "reject")

        parsed_dashboard = parse_vc_command("/vc dashboard acme 30d")
        assert parsed_dashboard is not None
        self.assertEqual(parsed_dashboard["tool_name"], "vc_ops_dashboard")
        self.assertEqual(parsed_dashboard["tool_input"]["startup_id"], "acme")

    def test_natural_language_collect(self) -> None:
        parsed = parse_vc_command("VC acme 14일 수집해줘")
        assert parsed is not None
        self.assertEqual(parsed["tool_name"], "vc_collect_bundle")
        self.assertEqual(parsed["tool_input"]["action"], "collect")
        self.assertEqual(parsed["tool_input"]["period"], "14d")

    def test_invalid_usage(self) -> None:
        with self.assertRaises(ValueError):
            parse_vc_command("/vc collect")

    def test_help_command(self) -> None:
        parsed = parse_vc_command("/vc")
        assert parsed is not None
        self.assertEqual(parsed["tool_name"], "__vc_help__")
        parsed2 = parse_vc_command("/vc help")
        assert parsed2 is not None
        self.assertEqual(parsed2["tool_name"], "__vc_help__")


if __name__ == "__main__":
    unittest.main()
