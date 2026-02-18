from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest

from self_expansion import SelfExpansionLoop


def build_tool_code(name: str) -> str:
    return f"""#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

TOOL_SPEC = {{
    "name": "{name}",
    "description": "auto generated tool",
    "version": "1.0.0",
    "input_schema": {{
        "type": "object",
        "properties": {{
            "text": {{"type": "string"}}
        }}
    }}
}}


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {{"ok": True, "echo": str(input_data.get("text", ""))}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()
    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0
        input_data = json.loads(args.tool_input_json) if args.tool_input_json else {{}}
        context = json.loads(args.tool_context_json) if args.tool_context_json else {{}}
        print(json.dumps(run(input_data, context), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({{"ok": False, "error": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
"""


class FakeExecutor:
    def __init__(self, tools_dir: Path) -> None:
        self.tools_dir = tools_dir
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.sync_count = 0

    def describe_tools(self) -> list[dict]:
        return [{"name": "echo_tool", "source": "custom", "description": "", "required": [], "file": "tools/echo_tool.py"}]

    def run_tool(self, name: str, input_data: dict) -> tuple[str, bool]:
        if name != "create_or_update_custom_tool_file":
            return json.dumps({"error": "unsupported"}), True
        file_name = str(input_data.get("file_name", "")).strip()
        content = str(input_data.get("content", ""))
        if not file_name:
            return json.dumps({"error": "missing file_name"}), True
        target = (self.tools_dir / file_name).resolve()
        target.write_text(content, encoding="utf-8")
        return json.dumps({"file": str(target)}, ensure_ascii=False), False

    def sync_custom_tools(self, force: bool = False) -> None:
        self.sync_count += 1


class TestSelfExpansion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = Path.cwd().resolve() / "logs" / "test_runtime_self_expansion"
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)
        cls.runtime_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.runtime_root.exists():
            shutil.rmtree(cls.runtime_root)

    def test_run_cycle_creates_tool_from_feedback(self) -> None:
        case_dir = self.runtime_root / "create_case"
        tools_dir = case_dir / "tools"
        feedback_file = case_dir / "logs/agent_feedback.jsonl"
        feedback_file.parent.mkdir(parents=True, exist_ok=True)
        feedback_file.write_text(
            json.dumps({"event": "react_feedback", "detail": {"kind": "max_tool_rounds"}}) + "\n",
            encoding="utf-8",
        )
        fake_exec = FakeExecutor(tools_dir=tools_dir)

        def planner(_payload: dict) -> dict:
            return {
                "action": "create_or_update_tool",
                "reason": "unit test",
                "tool_file": "auto_fix_tool.py",
                "tool_name": "auto_fix_tool",
                "code": build_tool_code("auto_fix_tool"),
            }

        loop = SelfExpansionLoop(
            api_key="",
            model="",
            workdir=str(case_dir),
            custom_tool_dir="tools",
            tool_executor=fake_exec,
            planner=planner,
            enabled=True,
            auto_apply=True,
            feedback_files=["logs/agent_feedback.jsonl"],
            state_file="logs/self_expansion_state.json",
            actions_file="logs/self_expansion_actions.jsonl",
            max_events_per_cycle=3,
        )
        result = loop.run_cycle(trigger="unit")
        self.assertTrue(result["changed"], msg=result)
        self.assertTrue((tools_dir / "auto_fix_tool.py").exists())
        self.assertEqual(fake_exec.sync_count, 1)

        second = loop.run_cycle(trigger="unit-second")
        self.assertFalse(second["changed"])
        self.assertEqual(second["processed_events"], 0)

    def test_run_cycle_blocks_path_escape(self) -> None:
        case_dir = self.runtime_root / "path_case"
        tools_dir = case_dir / "tools"
        feedback_file = case_dir / "logs/agent_feedback.jsonl"
        feedback_file.parent.mkdir(parents=True, exist_ok=True)
        feedback_file.write_text(
            json.dumps({"event": "react_feedback", "detail": {"kind": "repeated_tool_call"}}) + "\n",
            encoding="utf-8",
        )
        fake_exec = FakeExecutor(tools_dir=tools_dir)

        def planner(_payload: dict) -> dict:
            return {
                "action": "create_or_update_tool",
                "reason": "bad path",
                "tool_file": "../evil.py",
                "tool_name": "evil",
                "code": build_tool_code("evil"),
            }

        loop = SelfExpansionLoop(
            api_key="",
            model="",
            workdir=str(case_dir),
            custom_tool_dir="tools",
            tool_executor=fake_exec,
            planner=planner,
            enabled=True,
            auto_apply=True,
            feedback_files=["logs/agent_feedback.jsonl"],
            state_file="logs/self_expansion_state.json",
            actions_file="logs/self_expansion_actions.jsonl",
            max_events_per_cycle=3,
        )
        result = loop.run_cycle(trigger="unit")
        self.assertFalse(result["changed"], msg=result)
        self.assertIn("tool_file", json.dumps(result, ensure_ascii=False))
