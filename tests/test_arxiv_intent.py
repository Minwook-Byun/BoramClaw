from __future__ import annotations

from pathlib import Path
import unittest

from main import ToolExecutor, parse_arxiv_quick_request


class TestArxivIntent(unittest.TestCase):
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

    def test_quick_request_requires_retrieval_intent(self) -> None:
        payload = parse_arxiv_quick_request("저게 딥시크 관련 논문이야?")
        self.assertIsNone(payload)

    def test_quick_request_extracts_deepseek_keyword(self) -> None:
        payload = parse_arxiv_quick_request("아카이브에서 DeepSeek 관련 논문 3개 요약해줘")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["max_papers"], 3)
        self.assertIn("deepseek", payload.get("keywords", []))

    def test_quick_request_maps_old_papers_to_wide_window(self) -> None:
        payload = parse_arxiv_quick_request("아카이브에서 딥시크 예전 논문 2편 찾아줘")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["max_papers"], 2)
        self.assertGreaterEqual(int(payload["days_back"]), 365)

    def test_schema_selection_skips_arxiv_for_non_action_question(self) -> None:
        _, report = self.executor.select_tool_specs_for_prompt("저게 딥시크 관련 논문이야?")
        self.assertNotIn("arxiv_daily_digest", report.get("selected_tools", []))

    def test_schema_selection_includes_arxiv_for_retrieval_request(self) -> None:
        _, report = self.executor.select_tool_specs_for_prompt("아카이브에서 딥시크 논문 찾아서 요약해줘")
        self.assertIn("arxiv_daily_digest", report.get("selected_tools", []))

