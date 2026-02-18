from __future__ import annotations

import json
from pathlib import Path
import unittest

from main import ToolExecutor


class TestToolSpecs(unittest.TestCase):
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

    def test_custom_tools_have_version(self) -> None:
        specs = [s for s in self.executor.tool_specs if s.get("name") not in {
            "list_files",
            "read_file",
            "read_text_file",
            "write_file",
            "save_text_file",
            "run_shell",
            "run_python",
            "list_custom_tools",
            "reload_custom_tools",
            "tool_registry_status",
            "create_or_update_custom_tool_file",
            "delete_custom_tool_file",
            "schedule_daily_tool",
            "list_scheduled_jobs",
            "delete_scheduled_job",
            "run_due_scheduled_jobs",
        }]
        self.assertGreaterEqual(len(specs), 3)
        for spec in specs:
            self.assertIn("version", spec, msg=f"tool missing version: {json.dumps(spec, ensure_ascii=False)}")

    def test_arxiv_tool_loaded(self) -> None:
        names = [spec.get("name") for spec in self.executor.tool_specs]
        self.assertIn("arxiv_daily_digest", names)

    def test_integration_tools_loaded(self) -> None:
        names = [spec.get("name") for spec in self.executor.tool_specs]
        self.assertIn("github_pr_digest", names)
        self.assertIn("google_calendar_agenda", names)
        self.assertIn("stock_price_watch", names)
        self.assertIn("semantic_web_snapshot", names)
        self.assertIn("onchain_wallet_snapshot", names)
        self.assertIn("telegram_send_message", names)

    def test_tool_files_with_spec_define_dunder_version(self) -> None:
        tools_dir = Path.cwd() / "tools"
        for path in sorted(tools_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "TOOL_SPEC" not in text:
                continue
            self.assertIn("__version__", text, msg=f"missing __version__ in {path.name}")
