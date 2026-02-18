from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest

from main import ToolExecutor


def build_cli_tool_code(name: str) -> str:
    return f"""from __future__ import annotations
import argparse
import json
import sys
from typing import Any

TOOL_SPEC = {{
    "name": "{name}",
    "description": "test tool",
    "input_schema": {{
        "type": "object",
        "properties": {{
            "text": {{"type": "string"}}
        }}
    }}
}}

def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    text = str(input_data.get("text", ""))
    return {{"echo": text, "workdir": context.get("workdir", "")}}

def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {{}}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed

def main() -> int:
    parser = argparse.ArgumentParser(description="{name} cli")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()
    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0
        input_data = _load_json_object(args.tool_input_json)
        context = _load_json_object(args.tool_context_json)
        print(json.dumps(run(input_data, context), ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({{"ok": False, "error": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
"""


def build_network_tool_code(name: str) -> str:
    return f"""from __future__ import annotations
import argparse
import json
import sys
import urllib.request
from typing import Any

TOOL_SPEC = {{
    "name": "{name}",
    "description": "network test tool",
    "input_schema": {{
        "type": "object",
        "properties": {{}}
    }}
}}

def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    with urllib.request.urlopen("https://example.com", timeout=2) as resp:
        return {{"status": resp.status}}

def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {{}}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed

def main() -> int:
    parser = argparse.ArgumentParser(description="{name} cli")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()
    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0
        input_data = _load_json_object(args.tool_input_json)
        context = _load_json_object(args.tool_context_json)
        print(json.dumps(run(input_data, context), ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({{"ok": False, "error": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
"""


class TestAgentCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path.cwd().resolve()
        cls.runtime_root = cls.repo_root / "logs" / "test_runtime_agent_core"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def setUp(self) -> None:
        self.case_root = self.runtime_root / self._testMethodName
        if self.case_root.exists():
            shutil.rmtree(self.case_root)
        self.case_root.mkdir(parents=True, exist_ok=True)
        self.case_tools = self.case_root / "tools"
        self.case_schedules = self.case_root / "schedules"
        self.case_tools.mkdir(parents=True, exist_ok=True)
        self.case_schedules.mkdir(parents=True, exist_ok=True)
        (self.case_tools / "ping_tool.py").write_text(
            build_cli_tool_code("ping_tool"),
            encoding="utf-8",
        )
        self.executor = ToolExecutor(
            workdir=str(self.repo_root),
            custom_tool_dir=str(self.case_tools),
            schedule_file=str(self.case_schedules / "jobs.json"),
            strict_workdir_only=True,
        )
        self.case_tools_rel = self.case_tools.relative_to(self.repo_root).as_posix()
        self.case_root_rel = self.case_root.relative_to(self.repo_root).as_posix()

    def tearDown(self) -> None:
        self.executor.shutdown()
        if self.case_root.exists():
            shutil.rmtree(self.case_root)

    def test_custom_tool_discovered_from_filesystem(self) -> None:
        payload = self.executor._tool_list_custom_tools()
        self.assertIn("ping_tool.py", payload["files"])
        self.assertIn("ping_tool", payload["loaded_tools"])

    def test_custom_tool_runs_in_external_process_contract(self) -> None:
        result_text, is_error = self.executor.run_tool("ping_tool", {"text": "hello"})
        self.assertFalse(is_error, msg=result_text)
        payload = json.loads(result_text)
        self.assertEqual(payload["tool"], "ping_tool")
        nested = json.loads(payload["result"])
        self.assertEqual(nested["echo"], "hello")

    def test_tool_registry_reports_external_process_mode(self) -> None:
        status = self.executor._tool_registry_status()
        self.assertEqual(status["mode"], "filesystem_external_process")

    def test_read_text_file_alias(self) -> None:
        file_path = self.case_root / "notes.txt"
        file_path.write_text("a\nb\nc\n", encoding="utf-8")
        rel_path = file_path.relative_to(self.repo_root).as_posix()
        result_text, is_error = self.executor.run_tool(
            "read_text_file",
            {"path": rel_path, "start_line": 1, "end_line": 2},
        )
        self.assertFalse(is_error, msg=result_text)
        payload = json.loads(result_text)
        self.assertIn("1: a", payload["content"])
        self.assertIn("2: b", payload["content"])

    def test_save_text_file_restricts_to_tools_directory(self) -> None:
        allowed_path = f"{self.case_tools_rel}/new_tool.py"
        ok_text, ok_error = self.executor.run_tool(
            "save_text_file",
            {"path": allowed_path, "content": "x=1\n"},
        )
        self.assertFalse(ok_error, msg=ok_text)
        disallowed_path = f"{self.case_root_rel}/logs/nope.txt"
        bad_text, bad_error = self.executor.run_tool(
            "save_text_file",
            {"path": disallowed_path, "content": "x=1\n"},
        )
        self.assertTrue(bad_error)
        self.assertIn("tools/ 디렉토리 내부", bad_text)

    def test_run_shell_blocks_parent_traversal_in_strict_mode(self) -> None:
        result_text, is_error = self.executor.run_tool("run_shell", {"command": "ls .."})
        self.assertTrue(is_error)
        self.assertIn("상위 디렉토리 이동", result_text)

    def test_run_shell_blocks_network_commands_in_strict_mode(self) -> None:
        result_text, is_error = self.executor.run_tool("run_shell", {"command": "curl https://example.com"})
        self.assertTrue(is_error)
        self.assertIn("네트워크 명령", result_text)

    def test_custom_tool_network_access_blocked_in_strict_mode(self) -> None:
        (self.case_tools / "net_tool.py").write_text(
            build_network_tool_code("net_tool"),
            encoding="utf-8",
        )
        self.executor.sync_custom_tools(force=True)
        result_text, is_error = self.executor.run_tool("net_tool", {})
        self.assertTrue(is_error)
        self.assertIn("network", result_text.lower())

    def test_schema_selection_cache_hits_on_same_prompt(self) -> None:
        _, report1 = self.executor.select_tool_specs_for_prompt("tools 폴더 목록 확인")
        _, report2 = self.executor.select_tool_specs_for_prompt("tools 폴더 목록 확인")
        self.assertFalse(report1["cache_hit"])
        self.assertTrue(report2["cache_hit"])

    def test_schema_cache_invalidates_when_tool_files_change(self) -> None:
        self.executor.select_tool_specs_for_prompt("cache warmup")
        status_before = self.executor._tool_registry_status()
        self.assertGreaterEqual(status_before["tool_schema_cache"]["entries"], 1)

        (self.case_tools / "second_tool.py").write_text(
            build_cli_tool_code("second_tool"),
            encoding="utf-8",
        )
        self.executor.sync_custom_tools()
        status_after = self.executor._tool_registry_status()
        self.assertEqual(status_after["tool_schema_cache"]["entries"], 0)

    def test_create_or_update_custom_tool_file_requires_contract_markers(self) -> None:
        result_text, is_error = self.executor.run_tool(
            "create_or_update_custom_tool_file",
            {"file_name": "bad.py", "content": "print(1)\n"},
        )
        self.assertTrue(is_error)
        self.assertIn("필수 계약 마커", result_text)

    def test_schedule_daily_custom_tool_stores_custom_file_reference(self) -> None:
        result_text, is_error = self.executor.run_tool(
            "schedule_daily_tool",
            {"tool_name": "ping_tool", "time": "09:00", "tool_input": {"text": "daily"}},
        )
        self.assertFalse(is_error, msg=result_text)
        payload = json.loads(result_text)
        tool_ref = payload["job"]["tool_ref"]
        self.assertEqual(tool_ref["kind"], "custom_file")
        self.assertEqual(tool_ref["tool_name"], "ping_tool")
