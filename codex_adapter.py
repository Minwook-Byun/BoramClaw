from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any


def _split_command(command_text: str) -> list[str]:
    parts = shlex.split((command_text or "").strip())
    return parts or ["codex"]


def is_codex_command_available(command_text: str = "codex") -> bool:
    parts = _split_command(command_text)
    return shutil.which(parts[0]) is not None


class CodexCLIError(RuntimeError):
    pass


def _string_list(values: Any, *, limit: int = 6) -> list[str]:
    if not isinstance(values, list):
        return []
    rows: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _format_wrapup_evidence(evidence: dict[str, Any] | None) -> list[str]:
    if not isinstance(evidence, dict) or not evidence:
        return ["- evidence 없음"]

    touched_repos = [repo for repo in evidence.get("touched_repos", []) if isinstance(repo, dict)]
    prompt_samples = _string_list(evidence.get("prompt_samples"), limit=6)
    workdirs = _string_list(evidence.get("active_workdirs"), limit=6)
    memory_tail = _string_list(evidence.get("session_memory_tail"), limit=6)
    git_totals = evidence.get("git_totals", {}) if isinstance(evidence.get("git_totals", {}), dict) else {}
    feedback_counts = evidence.get("feedback_counts", {}) if isinstance(evidence.get("feedback_counts", {}), dict) else {}
    top_correction_hints = [
        item for item in evidence.get("top_correction_hints", []) if isinstance(item, dict)
    ]

    lines = [
        f"- collected_at: {str(evidence.get('collected_at', '')).strip() or '-'}",
        f"- prompt_count: {int(evidence.get('prompt_count', 0) or 0)}",
        f"- rollout_count: {int(evidence.get('rollout_count', 0) or 0)}",
        (
            f"- feedback_counts: accepted={int(feedback_counts.get('accepted', 0) or 0)}, "
            f"corrected={int(feedback_counts.get('corrected', 0) or 0)}, "
            f"retried={int(feedback_counts.get('retried', 0) or 0)}, "
            f"ambiguous={int(feedback_counts.get('ambiguous', 0) or 0)}"
        ),
        (
            f"- git_totals: repo={int(git_totals.get('repo_count', 0) or 0)}, "
            f"modified={int(git_totals.get('modified_files', 0) or 0)}, "
            f"untracked={int(git_totals.get('untracked_files', 0) or 0)}, "
            f"commits={int(git_totals.get('commit_count', 0) or 0)}"
        ),
    ]

    if prompt_samples:
        lines.append("Prompt samples:")
        lines.extend(f"- {item}" for item in prompt_samples)
    if workdirs:
        lines.append("Active workdirs:")
        lines.extend(f"- {item}" for item in workdirs)
    if top_correction_hints:
        lines.append("Correction hints:")
        for item in top_correction_hints[:5]:
            label = str(item.get("label", "")).strip()
            count = int(item.get("count", 0) or 0)
            examples = _string_list(item.get("examples"), limit=1)
            if not label:
                continue
            suffix = f" example={examples[0]}" if examples else ""
            lines.append(f"- {label} ({count}){suffix}")
    if touched_repos:
        lines.append("Touched repos:")
        for repo in touched_repos[:4]:
            changed_files = ", ".join(_string_list(repo.get("changed_files"), limit=5)) or "-"
            recent_commits = [
                item
                for item in repo.get("recent_commits", [])
                if isinstance(item, dict) and (str(item.get("subject", "")).strip() or str(item.get("sha", "")).strip())
            ]
            commit_summary = ", ".join(
                f"{str(item.get('sha', '')).strip()} {str(item.get('subject', '')).strip()}".strip()
                for item in recent_commits[:3]
            ) or "-"
            lines.append(
                (
                    f"- {str(repo.get('name', '')).strip() or repo.get('path', '-')}: "
                    f"branch={str(repo.get('branch', '-') or '-')}, "
                    f"modified={int(repo.get('modified_files', 0) or 0)}, "
                    f"untracked={int(repo.get('untracked_files', 0) or 0)}, "
                    f"changed_files={changed_files}, commits={commit_summary}"
                )
            )
    if memory_tail:
        lines.append("Session memory tail:")
        lines.extend(f"- {item}" for item in memory_tail)
    return lines


def build_wrapup_prompt(
    *,
    session_memory: list[str],
    focus: str = "",
    evidence: dict[str, Any] | None = None,
) -> str:
    prompt_lines = [
        "당신은 evidence-first 개발 세션 wrap-up assistant입니다.",
        "추측하지 말고 아래 근거를 우선 사용하세요. 근거가 없으면 '근거 부족'이라고 명시하세요.",
        "응답은 한국어 Markdown으로 작성하고, 반드시 아래 섹션 제목을 정확히 사용하세요.",
        "## 오늘 실제로 한 일",
        "## 프롬프트 흐름 해석",
        "## 남은 일 / 리스크",
        "## 다음 세션 첫 액션",
        "각 섹션에는 2~5개의 bullet을 쓰고, 가능하면 레포명/파일명/프롬프트 표현을 직접 언급하세요.",
        "다음 세션 첫 액션 섹션은 numbered list 1~3으로 작성하세요.",
    ]
    if focus.strip():
        prompt_lines.append(f"사용자 포커스: {focus.strip()}")
    prompt_lines.append("")
    prompt_lines.append("[Evidence]")
    prompt_lines.extend(_format_wrapup_evidence(evidence))
    prompt_lines.append("")
    prompt_lines.append("[Session Memory]")
    memory_lines = [str(item).strip() for item in session_memory[-12:] if str(item).strip()]
    prompt_lines.extend(memory_lines or ["- 세션 메모가 비어 있습니다. 위 evidence만으로 정리하세요."])
    prompt_lines.append("")
    prompt_lines.append("짧게 끝내지 말고, 오늘 무엇을 했는지와 왜 그게 중요한지를 evidence 기반으로 정리하세요.")
    return "\n".join(prompt_lines).strip()


class CodexRunner:
    def __init__(
        self,
        *,
        command: str = "codex",
        model: str = "",
        workdir: str = ".",
        sandbox_mode: str = "workspace-write",
        approval_policy: str = "never",
    ) -> None:
        self.command = command
        self.model = model.strip()
        self.workdir = str(Path(workdir).resolve())
        self.sandbox_mode = sandbox_mode
        self.approval_policy = approval_policy

    def _base_command(self) -> list[str]:
        cmd = _split_command(self.command)
        if self.model:
            cmd.extend(["-m", self.model])
        if self.sandbox_mode:
            cmd.extend(["-s", self.sandbox_mode])
        if self.approval_policy:
            cmd.extend(["-a", self.approval_policy])
        return cmd

    def _run(self, args: list[str], *, timeout_seconds: int = 600) -> str:
        if not is_codex_command_available(self.command):
            raise CodexCLIError(f"Codex CLI를 찾을 수 없습니다: {self.command}")
        try:
            completed = subprocess.run(
                args,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CodexCLIError(f"Codex CLI 실행 파일을 찾을 수 없습니다: {self.command}") from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexCLIError(f"Codex CLI 실행 시간이 초과되었습니다 ({timeout_seconds}초).") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise CodexCLIError(detail or f"Codex CLI가 종료 코드 {completed.returncode}로 실패했습니다.")
        return completed.stdout.strip()

    def exec_prompt(self, prompt: str, *, timeout_seconds: int = 600) -> str:
        with tempfile.NamedTemporaryFile(prefix="boramclaw_codex_", suffix=".txt", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            args = self._base_command()
            args.extend(
                [
                    "exec",
                    "--skip-git-repo-check",
                    "--color",
                    "never",
                    "-C",
                    self.workdir,
                    "-o",
                    str(output_path),
                    prompt,
                ]
            )
            self._run(args, timeout_seconds=timeout_seconds)
            result = output_path.read_text(encoding="utf-8", errors="replace").strip()
            if not result:
                raise CodexCLIError("Codex exec 결과가 비어 있습니다.")
            return result
        finally:
            output_path.unlink(missing_ok=True)

    def review(self, prompt: str = "", *, uncommitted: bool = True, timeout_seconds: int = 600) -> str:
        args = self._base_command()
        args.extend(["review"])
        if uncommitted:
            args.append("--uncommitted")
        if prompt.strip():
            args.append(prompt.strip())
        return self._run(args, timeout_seconds=timeout_seconds)


class CodexCLIChat:
    def __init__(
        self,
        *,
        command: str = "codex",
        model: str = "",
        workdir: str = ".",
        system_prompt: str = "",
        force_tool_use: bool = False,
    ) -> None:
        self.runner = CodexRunner(command=command, model=model, workdir=workdir)
        self.system_prompt = system_prompt
        self.force_tool_use = force_tool_use
        self.history: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def reset_session(self, summary: str = "") -> None:
        self.history = []
        note = summary.strip()
        if note:
            self.history.append({"role": "assistant", "content": f"이전 세션 요약:\n{note}"})

    def _materialize_tool_manifest(self, tools: list[dict[str, Any]]) -> Path | None:
        normalized_tools: list[dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            file_path = str(item.get("file", "")).strip()
            cli_examples: list[str] = []
            if file_path:
                context_json = json.dumps({"workdir": self.runner.workdir}, ensure_ascii=False)
                cli_examples.append(
                    f"python3 {shlex.quote(file_path)} --tool-input-json '<json>' --tool-context-json {shlex.quote(context_json)}"
                )
            cli_examples.append(f"/tool {name} {{...}}")
            normalized_tools.append(
                {
                    "name": name,
                    "source": str(item.get("source", "builtin") or "builtin"),
                    "description": str(item.get("description", "") or ""),
                    "required": item.get("required", []),
                    "input_schema": item.get("input_schema", {}),
                    "file": file_path,
                    "network_access": bool(item.get("network_access", False)),
                    "cli_examples": cli_examples,
                }
            )
        if not normalized_tools:
            return None
        with tempfile.NamedTemporaryFile(
            prefix=".boramclaw_codex_tools_",
            suffix=".json",
            delete=False,
            dir=self.runner.workdir,
        ) as handle:
            path = Path(handle.name)
        payload = {
            "workdir": self.runner.workdir,
            "tool_count": len(normalized_tools),
            "tools": normalized_tools,
            "usage_hint": (
                "custom tool은 file 경로와 cli_examples를 참고해 직접 실행할 수 있고, "
                "builtin tool은 해당 설명과 schema를 참고해 작업 디렉터리를 탐색하세요."
            ),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _build_prompt(
        self,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        manifest_path: Path | None = None,
    ) -> str:
        lines: list[str] = []
        if self.system_prompt.strip():
            lines.append("[System]")
            lines.append(self.system_prompt.strip())
            lines.append("")
        if tools:
            tool_names = ", ".join(str(item.get("name", "")).strip() for item in tools if str(item.get("name", "")).strip())
            if tool_names:
                lines.append("[BoramClaw Tool Context]")
                lines.append(
                    "Codex provider에서는 BoramClaw의 native tool loop가 비활성화되어 있습니다. "
                    "대신 선택된 도구 schema와 실행 힌트를 구조화된 manifest로 제공합니다."
                )
                lines.append(f"Selected tools: {tool_names}")
                if manifest_path is not None:
                    lines.append(f"Manifest file: {manifest_path}")
                    lines.append(
                        "필요하면 manifest JSON을 읽고, custom tool의 경우 file/cli_examples를 이용해 직접 실행한 뒤 결과를 반영하세요."
                    )
                lines.append("")
        if self.history:
            lines.append("[Recent Conversation]")
            for item in self.history[-8:]:
                lines.append(f"{item['role']}: {item['content']}")
            lines.append("")
        lines.append("[User]")
        lines.append(user_message.strip())
        lines.append("")
        lines.append("최종 응답은 한국어로만 작성하세요.")
        return "\n".join(lines).strip()

    def ask(
        self,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        tool_runner: Any | None = None,
        on_tool_event: Any | None = None,
    ) -> str:
        del tool_runner
        del on_tool_event
        with self._lock:
            manifest_path = self._materialize_tool_manifest(tools or []) if tools else None
            try:
                prompt = self._build_prompt(user_message, tools=tools, manifest_path=manifest_path)
                answer = self.runner.exec_prompt(prompt)
                self.history.append({"role": "user", "content": user_message})
                self.history.append({"role": "assistant", "content": answer})
                return answer
            finally:
                if manifest_path is not None:
                    manifest_path.unlink(missing_ok=True)

    def consume_pending_usage(self) -> dict[str, int]:
        return {}

    def get_total_usage(self) -> dict[str, int]:
        return {}


class AdvancedWorkflowRunner:
    def __init__(
        self,
        *,
        provider: str,
        codex_command: str,
        codex_model: str,
        workdir: str,
        enabled: bool,
    ) -> None:
        self.provider = provider.strip().lower() or "codex"
        self.enabled = enabled
        self.codex = CodexRunner(command=codex_command, model=codex_model, workdir=workdir)
        self.review_presets: dict[str, str] = {
            "engineering": (
                "현재 변경사항을 코드 리뷰하세요. 버그, 회귀 위험, 잘못된 가정, 빠진 테스트를 우선순위대로 한국어로 정리하세요. "
                "finding 중심으로 시작하고, 파일/행 단서를 최대한 구체화하세요."
            ),
            "pm": (
                "현재 변경사항을 PM 관점에서 리뷰하세요. 사용자 흐름, activation friction, scope clarity, instrumentation gap, "
                "docs mismatch, adoption risk를 한국어로 정리하세요."
            ),
            "cpo": (
                "현재 변경사항을 CPO 관점에서 리뷰하세요. ICP 적합성, 핵심 가치 전달, trust/privacy, onboarding, retention loop, "
                "roadmap 우선순위 관점의 리스크와 개선점을 한국어로 정리하세요."
            ),
        }

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if self.provider != "codex":
            return False
        return is_codex_command_available(self.codex.command)

    def render_status(self) -> str:
        enabled_text = "on" if self.enabled else "off"
        available_text = "ready" if self.is_available() else "unavailable"
        lines = [
            "Advanced 워크플로우 상태",
            f"- provider: {self.provider}",
            f"- enabled: {enabled_text}",
            f"- backend: {self.codex.command}",
            f"- availability: {available_text}",
            "",
            "사용 가능한 고급 흐름",
            "- /delegate <요청> : 멀티에이전트 라우팅",
            "- /review [engineering|pm|cpo] [지시사항] : Codex 기반 인터랙티브 리뷰",
            "- /wrapup [포커스] : Codex 기반 세션 랩업",
            "",
            "리뷰 preset",
            "- engineering: 코드 품질/회귀/테스트",
            "- pm: 사용자 흐름/activation/scope",
            "- cpo: 포지셔닝/온보딩/리텐션/trust",
        ]
        if self.provider == "codex" and not is_codex_command_available(self.codex.command):
            lines.append("")
            lines.append("주의: Codex CLI가 보이지 않아 review/wrapup은 실행되지 않습니다.")
        return "\n".join(lines)

    def run_review(self, *, preset: str = "engineering", prompt: str = "") -> str:
        if not self.enabled:
            raise CodexCLIError("Advanced 워크플로우가 비활성화되어 있습니다.")
        if self.provider != "codex":
            raise CodexCLIError(f"지원하지 않는 advanced provider입니다: {self.provider}")
        normalized_preset = preset.strip().lower() or "engineering"
        base_prompt = self.review_presets.get(normalized_preset, self.review_presets["engineering"])
        extra = prompt.strip()
        review_prompt = base_prompt if not extra else f"{base_prompt}\n\n추가 지시사항:\n{extra}"
        return self.codex.review(review_prompt, uncommitted=True)

    def run_wrapup(
        self,
        *,
        session_memory: list[str],
        focus: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> str:
        if not self.enabled:
            raise CodexCLIError("Advanced 워크플로우가 비활성화되어 있습니다.")
        if self.provider != "codex":
            raise CodexCLIError(f"지원하지 않는 advanced provider입니다: {self.provider}")
        prompt = build_wrapup_prompt(session_memory=session_memory, focus=focus, evidence=evidence)
        return self.codex.exec_prompt(prompt)
