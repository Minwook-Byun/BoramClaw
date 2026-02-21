from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from main import ToolExecutor
from runtime_commands import parse_integration_command


class TestMainExternalIntegrationCommands(unittest.TestCase):
    def test_integration_command_can_run_via_tool_executor(self) -> None:
        repo_root = Path(__file__).parent.parent.resolve()
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "config").mkdir(parents=True, exist_ok=True)
            (workdir / "data").mkdir(parents=True, exist_ok=True)
            (workdir / "vault").mkdir(parents=True, exist_ok=True)

            executor = ToolExecutor(
                workdir=str(workdir),
                custom_tool_dir=str(repo_root / "tools"),
                schedule_file=str(workdir / "schedules" / "jobs.json"),
                strict_workdir_only=False,
            )
            try:
                parsed_connect = parse_integration_command("/integration connect acme google_drive")
                assert parsed_connect is not None
                out_connect, is_error_connect = executor.run_tool(
                    parsed_connect["tool_name"],
                    parsed_connect["tool_input"],
                )
                self.assertFalse(is_error_connect, msg=out_connect)
                connect_outer = json.loads(out_connect)
                connect_data = json.loads(str(connect_outer.get("result", "{}")))
                self.assertTrue(connect_data.get("success"))

                parsed_status = parse_integration_command("/integration status acme")
                assert parsed_status is not None
                out_status, is_error_status = executor.run_tool(
                    parsed_status["tool_name"],
                    parsed_status["tool_input"],
                )
                self.assertFalse(is_error_status, msg=out_status)
                status_outer = json.loads(out_status)
                status_data = json.loads(str(status_outer.get("result", "{}")))
                self.assertTrue(status_data.get("success"))
                self.assertGreaterEqual(int(status_data.get("count", 0) or 0), 1)
            finally:
                executor.shutdown()


if __name__ == "__main__":
    unittest.main()
