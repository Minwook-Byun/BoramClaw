from __future__ import annotations

import re
import unittest

from runtime_commands import (
    INTEGRATION_PRIMARY_SUBCOMMANDS,
    VC_PRIMARY_SUBCOMMANDS,
    format_integration_help,
    format_vc_help,
    format_permissions_map,
    format_user_output,
    parse_arxiv_quick_request,
    parse_deep_weekly_quick_request,
    parse_feedback_command,
    parse_memory_command,
    parse_reflexion_command,
    parse_schedule_arxiv_command,
    parse_set_permission_command,
    parse_integration_command,
    parse_tool_command,
    parse_vc_command,
)


class TestRuntimeCommands(unittest.TestCase):
    def test_parse_tool_command(self) -> None:
        self.assertEqual(parse_tool_command("/tool list_files"), ("list_files", {}))
        name, payload = parse_tool_command('/tool echo_tool {"text":"hello"}')  # type: ignore[misc]
        self.assertEqual(name, "echo_tool")
        self.assertEqual(payload["text"], "hello")

    def test_parse_permission_and_memory(self) -> None:
        self.assertEqual(parse_set_permission_command("/set-permission run_shell deny"), ("run_shell", "deny"))
        self.assertEqual(parse_memory_command("/memory latest 3"), {"action": "latest", "count": 3})
        self.assertEqual(parse_reflexion_command("/reflexion status"), {"action": "status"})

    def test_parse_feedback_command(self) -> None:
        self.assertEqual(parse_feedback_command("/feedback 루프 개선해"), "루프 개선해")
        with self.assertRaises(ValueError):
            parse_feedback_command("/feedback")

    def test_parse_arxiv_quick_request(self) -> None:
        payload = parse_arxiv_quick_request("아카이브에서 DeepSeek 관련 논문 2개 요약해줘")
        assert payload is not None
        self.assertEqual(payload["max_papers"], 2)
        self.assertIn("deepseek", payload.get("keywords", []))

    def test_parse_deep_weekly_quick_request(self) -> None:
        payload = parse_deep_weekly_quick_request("이번 주 깊이 있는 회고 작성해줘")
        assert payload is not None
        self.assertEqual(payload["days_back"], 7)

        payload_14 = parse_deep_weekly_quick_request("지난 14일 깊은 회고 정리해줘")
        assert payload_14 is not None
        self.assertEqual(payload_14["days_back"], 14)

        payload_2w = parse_deep_weekly_quick_request("deep_weekly_retrospective 2주 실행해줘")
        assert payload_2w is not None
        self.assertEqual(payload_2w["days_back"], 14)

        self.assertIsNone(parse_deep_weekly_quick_request("이번 주 회고 알려줘"))

    def test_parse_schedule_arxiv_command(self) -> None:
        cmd = parse_schedule_arxiv_command("/schedule-arxiv 08:00 deepseek llm")
        assert cmd is not None
        self.assertEqual(cmd["time"], "08:00")
        self.assertIn("deepseek", cmd["keywords"])

    def test_parse_vc_command(self) -> None:
        parsed = parse_vc_command("/vc collect acme 7d")
        assert parsed is not None
        self.assertEqual(parsed["tool_name"], "vc_collect_bundle")
        self.assertEqual(parsed["tool_input"]["period"], "7d")
        parsed_verify = parse_vc_command("/vc verify acme")
        assert parsed_verify is not None
        self.assertEqual(parsed_verify["tool_name"], "vc_remote_e2e_smoke")
        self.assertEqual(parsed_verify["tool_input"]["startup_id"], "acme")
        parsed_scope = parse_vc_command("/vc scope acme")
        assert parsed_scope is not None
        self.assertEqual(parsed_scope["tool_name"], "vc_scope_policy")
        parsed_dashboard = parse_vc_command("/vc dashboard acme 30d")
        assert parsed_dashboard is not None
        self.assertEqual(parsed_dashboard["tool_name"], "vc_ops_dashboard")
        parsed_approve = parse_vc_command("/vc approve 11111111-2222-3333-4444-555555555555 force by=alice")
        assert parsed_approve is not None
        self.assertTrue(parsed_approve["tool_input"]["force_high_risk"])
        self.assertEqual(parsed_approve["tool_input"]["approver"], "alice")

    def test_parse_integration_command(self) -> None:
        parsed_connect = parse_integration_command("/integration connect acme google_drive scopes=drive.readonly")
        assert parsed_connect is not None
        self.assertEqual(parsed_connect["tool_name"], "google_oauth_connect")
        self.assertEqual(parsed_connect["tool_input"]["action"], "connect")
        self.assertEqual(parsed_connect["tool_input"]["startup_id"], "acme")

        parsed_exchange = parse_integration_command(
            "/integration exchange 11111111-2222-3333-4444-555555555555 code=auth-code"
        )
        assert parsed_exchange is not None
        self.assertEqual(parsed_exchange["tool_input"]["action"], "exchange_code")
        self.assertEqual(parsed_exchange["tool_input"]["connection_id"], "11111111-2222-3333-4444-555555555555")

        parsed_refresh = parse_integration_command("/integration refresh 11111111-2222-3333-4444-555555555555 force")
        assert parsed_refresh is not None
        self.assertEqual(parsed_refresh["tool_input"]["action"], "refresh_token")
        self.assertTrue(bool(parsed_refresh["tool_input"].get("force_refresh")))

        parsed_status = parse_integration_command("/integration status acme google_drive")
        assert parsed_status is not None
        self.assertEqual(parsed_status["tool_input"]["action"], "status")

        parsed_test = parse_integration_command("/integration test 11111111-2222-3333-4444-555555555555")
        assert parsed_test is not None
        self.assertEqual(parsed_test["tool_input"]["action"], "test")

        parsed_revoke = parse_integration_command("/integration revoke 11111111-2222-3333-4444-555555555555")
        assert parsed_revoke is not None
        self.assertEqual(parsed_revoke["tool_input"]["action"], "revoke")

    def test_format_user_output_and_permissions(self) -> None:
        self.assertEqual(format_user_output('{"summary":"ok"}'), "ok")
        self.assertIn("run_shell", format_permissions_map({"run_shell": "prompt"}))

    def test_vc_help_and_parser_are_in_sync(self) -> None:
        help_text = format_vc_help()
        help_subcommands = set(re.findall(r"- /vc ([a-z-]+)", help_text))
        self.assertTrue(set(VC_PRIMARY_SUBCOMMANDS).issubset(help_subcommands))

        samples = {
            "help": "/vc help",
            "register": "/vc register acme Acme AI",
            "bind-folder": "/vc bind-folder acme http://127.0.0.1:8742 desktop_common",
            "collect": "/vc collect acme 7d",
            "report": "/vc report acme weekly",
            "verify": "/vc verify acme",
            "onboard": "/vc onboard acme 7d",
            "pending": "/vc pending acme",
            "approve": "/vc approve 11111111-2222-3333-4444-555555555555",
            "reject": "/vc reject 11111111-2222-3333-4444-555555555555 reason",
            "status": "/vc status acme",
            "scope": "/vc scope acme",
            "scope-audit": "/vc scope-audit acme 10 allow",
            "dashboard": "/vc dashboard acme 30d",
        }
        for subcommand in VC_PRIMARY_SUBCOMMANDS:
            sample = samples[subcommand]
            parsed = parse_vc_command(sample)
            assert parsed is not None

    def test_integration_help_and_parser_are_in_sync(self) -> None:
        help_text = format_integration_help()
        help_subcommands = set(re.findall(r"- /integration ([a-z-]+)", help_text))
        self.assertTrue(set(INTEGRATION_PRIMARY_SUBCOMMANDS).issubset(help_subcommands))

        samples = {
            "help": "/integration help",
            "connect": "/integration connect acme google_drive",
            "exchange": "/integration exchange 11111111-2222-3333-4444-555555555555 code=auth-code",
            "refresh": "/integration refresh 11111111-2222-3333-4444-555555555555 force",
            "test": "/integration test 11111111-2222-3333-4444-555555555555",
            "status": "/integration status acme google_drive",
            "revoke": "/integration revoke 11111111-2222-3333-4444-555555555555 manual",
        }
        for subcommand in INTEGRATION_PRIMARY_SUBCOMMANDS:
            sample = samples[subcommand]
            parsed = parse_integration_command(sample)
            assert parsed is not None


if __name__ == "__main__":
    unittest.main()
