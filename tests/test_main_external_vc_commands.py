from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from main import ToolExecutor
from runtime_commands import parse_vc_command


class TestMainExternalVCCommands(unittest.TestCase):
    def test_vc_command_can_run_via_tool_executor(self) -> None:
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
                parsed_register = parse_vc_command("/vc register acme Acme AI")
                assert parsed_register is not None
                out_register, is_error_register = executor.run_tool(
                    parsed_register["tool_name"],
                    parsed_register["tool_input"],
                )
                self.assertFalse(is_error_register, msg=out_register)
                register_outer = json.loads(out_register)
                register_data = json.loads(str(register_outer.get("result", "{}")))
                self.assertTrue(register_data.get("success"))

                parsed_status = parse_vc_command("/vc status acme")
                assert parsed_status is not None
                out_status, is_error_status = executor.run_tool(
                    parsed_status["tool_name"],
                    parsed_status["tool_input"],
                )
                self.assertFalse(is_error_status, msg=out_status)
                status_outer = json.loads(out_status)
                status_data = json.loads(str(status_outer.get("result", "{}")))
                self.assertTrue(status_data.get("success"))
                self.assertEqual(status_data.get("tenant", {}).get("startup_id"), "acme")
            finally:
                executor.shutdown()


if __name__ == "__main__":
    unittest.main()
