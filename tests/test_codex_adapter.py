from __future__ import annotations

from pathlib import Path
import json
import subprocess
import unittest
from unittest.mock import patch

from codex_adapter import AdvancedWorkflowRunner, CodexCLIChat, CodexRunner, build_wrapup_prompt


class TestCodexAdapter(unittest.TestCase):
    def test_codex_runner_exec_prompt_reads_output_file(self) -> None:
        written_path: Path | None = None
        captured_args: list[str] = []

        def fake_run(args, cwd, capture_output, text, timeout, check):  # noqa: ANN001,ANN201
            del cwd, capture_output, text, timeout, check
            nonlocal written_path
            captured_args[:] = list(args)
            output_idx = args.index("-o") + 1
            written_path = Path(args[output_idx])
            written_path.write_text("codex ok", encoding="utf-8")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        runner = CodexRunner(command="codex", model="o3", workdir=".")
        with patch("codex_adapter.is_codex_command_available", return_value=True), patch(
            "subprocess.run", side_effect=fake_run
        ):
            result = runner.exec_prompt("테스트")

        self.assertEqual(result, "codex ok")
        self.assertIsNotNone(written_path)
        assert written_path is not None
        self.assertFalse(written_path.exists())
        self.assertLess(captured_args.index("-a"), captured_args.index("exec"))
        self.assertLess(captured_args.index("-s"), captured_args.index("exec"))

    def test_codex_chat_maintains_recent_history(self) -> None:
        chat = CodexCLIChat(command="codex", workdir=".", system_prompt="system")
        with patch.object(chat.runner, "exec_prompt", return_value="첫 응답"):
            first = chat.ask("첫 질문")
        with patch.object(chat.runner, "exec_prompt", return_value="둘째 응답") as mocked_exec:
            second = chat.ask("둘째 질문")

        self.assertEqual(first, "첫 응답")
        self.assertEqual(second, "둘째 응답")
        prompt_text = mocked_exec.call_args.args[0]
        self.assertIn("첫 질문", prompt_text)
        self.assertIn("첫 응답", prompt_text)

    def test_codex_chat_writes_structured_tool_manifest(self) -> None:
        chat = CodexCLIChat(command="codex", workdir=".")
        observed_manifest: dict[str, object] = {}

        def fake_exec(prompt: str) -> str:
            marker = "Manifest file: "
            start = prompt.index(marker) + len(marker)
            manifest_path = Path(prompt[start:].splitlines()[0].strip())
            observed_manifest["path"] = str(manifest_path)
            observed_manifest["payload"] = json.loads(manifest_path.read_text(encoding="utf-8"))
            return "ok"

        tools = [
            {
                "name": "workday_recap",
                "description": "daily recap",
                "source": "custom",
                "file": "tools/workday_recap.py",
                "input_schema": {"type": "object", "properties": {"mode": {"type": "string"}}, "required": ["mode"]},
                "required": ["mode"],
                "network_access": False,
            }
        ]
        with patch.object(chat.runner, "exec_prompt", side_effect=fake_exec):
            answer = chat.ask("오늘 뭐 했지?", tools=tools)

        self.assertEqual(answer, "ok")
        payload = observed_manifest["payload"]
        assert isinstance(payload, dict)
        self.assertEqual(payload["tool_count"], 1)
        self.assertEqual(payload["tools"][0]["name"], "workday_recap")
        self.assertIn("cli_examples", payload["tools"][0])
        manifest_path = Path(str(observed_manifest["path"]))
        self.assertFalse(manifest_path.exists())

    def test_advanced_workflow_runner_status_mentions_commands(self) -> None:
        runner = AdvancedWorkflowRunner(
            provider="codex",
            codex_command="codex",
            codex_model="o3",
            workdir=".",
            enabled=True,
        )
        with patch("codex_adapter.is_codex_command_available", return_value=True):
            status = runner.render_status()
        self.assertIn("/review", status)
        self.assertIn("/wrapup", status)
        self.assertIn("cpo", status)

    def test_advanced_workflow_runner_review_preset_appends_extra_prompt(self) -> None:
        runner = AdvancedWorkflowRunner(
            provider="codex",
            codex_command="codex",
            codex_model="o3",
            workdir=".",
            enabled=True,
        )
        with patch.object(runner.codex, "review", return_value="review ok") as mocked_review:
            result = runner.run_review(preset="pm", prompt="모바일 onboarding도 봐줘")
        self.assertEqual(result, "review ok")
        review_prompt = mocked_review.call_args.args[0]
        self.assertIn("PM 관점", review_prompt)
        self.assertIn("모바일 onboarding도 봐줘", review_prompt)

    def test_build_wrapup_prompt_includes_evidence_sections(self) -> None:
        prompt = build_wrapup_prompt(
            session_memory=["user: 오늘 뭐 했지?", "assistant: wrapup 준비 중"],
            focus="OpenClaw식 회고",
            evidence={
                "prompt_count": 3,
                "prompt_samples": ["오늘 투두를 짜달라고", "자동 트리거 등도 붙여줘"],
                "feedback_counts": {"accepted": 1, "corrected": 2, "retried": 0, "ambiguous": 0},
                "top_correction_hints": [
                    {
                        "category": "prompt_analysis",
                        "label": "프롬프트 흐름 분석 포함",
                        "count": 2,
                        "examples": ["프롬프트 분석도 해주고"],
                    }
                ],
                "active_workdirs": ["/Users/boram/BoramClaw"],
                "touched_repos": [
                    {
                        "name": "BoramClaw",
                        "branch": "main",
                        "modified_files": 4,
                        "untracked_files": 2,
                        "changed_files": ["main.py", "session_timeseries.py"],
                        "recent_commits": [{"sha": "abc123", "subject": "feat: wrapup pipeline"}],
                    }
                ],
                "git_totals": {
                    "repo_count": 1,
                    "modified_files": 4,
                    "untracked_files": 2,
                    "commit_count": 1,
                },
            },
        )

        self.assertIn("## 오늘 실제로 한 일", prompt)
        self.assertIn("Prompt samples:", prompt)
        self.assertIn("feedback_counts:", prompt)
        self.assertIn("Correction hints:", prompt)
        self.assertIn("Touched repos:", prompt)
        self.assertIn("OpenClaw식 회고", prompt)
        self.assertIn("feat: wrapup pipeline", prompt)


if __name__ == "__main__":
    unittest.main()
