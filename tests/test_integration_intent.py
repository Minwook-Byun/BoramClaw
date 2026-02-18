from __future__ import annotations

from pathlib import Path
import unittest

from main import ToolExecutor


class TestIntegrationIntent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path.cwd().resolve()
        cls.executor = ToolExecutor(
            workdir=str(cls.repo_root),
            custom_tool_dir="tools",
            schedule_file="schedules/jobs.json",
            strict_workdir_only=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.executor.shutdown()

    def test_github_keyword_selects_tool(self) -> None:
        specs, report = self.executor.select_tool_specs_for_prompt("깃허브 PR 목록 요약해줘")
        names = [str(spec.get("name", "")) for spec in specs]
        self.assertIn("github_pr_digest", names, msg=str(report))

    def test_calendar_keyword_selects_tool(self) -> None:
        specs, report = self.executor.select_tool_specs_for_prompt("캘린더 일정 보여줘")
        names = [str(spec.get("name", "")) for spec in specs]
        self.assertIn("google_calendar_agenda", names, msg=str(report))

    def test_stock_keyword_selects_tool(self) -> None:
        specs, report = self.executor.select_tool_specs_for_prompt("SOXX 목표가 도달했는지 주식 가격 추적해줘")
        names = [str(spec.get("name", "")) for spec in specs]
        self.assertIn("stock_price_watch", names, msg=str(report))

    def test_semantic_snapshot_keyword_selects_tool(self) -> None:
        specs, report = self.executor.select_tool_specs_for_prompt("이 페이지 semantic snapshot 떠줘")
        names = [str(spec.get("name", "")) for spec in specs]
        self.assertIn("semantic_web_snapshot", names, msg=str(report))

    def test_onchain_keyword_selects_tool(self) -> None:
        specs, report = self.executor.select_tool_specs_for_prompt("이더리움 지갑 주소 잔액 조회해줘")
        names = [str(spec.get("name", "")) for spec in specs]
        self.assertIn("onchain_wallet_snapshot", names, msg=str(report))

    def test_messenger_keyword_selects_tool(self) -> None:
        specs, report = self.executor.select_tool_specs_for_prompt("텔레그램으로 메시지 보내줘")
        names = [str(spec.get("name", "")) for spec in specs]
        self.assertIn("telegram_send_message", names, msg=str(report))


if __name__ == "__main__":
    unittest.main()
