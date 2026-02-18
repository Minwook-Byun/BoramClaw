from __future__ import annotations

import ast
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
from typing import Any, Callable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


class SelfExpansionLoop:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        workdir: str,
        custom_tool_dir: str,
        tool_executor: Any,
        planner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        enabled: bool | None = None,
        auto_apply: bool | None = None,
        max_events_per_cycle: int | None = None,
        feedback_files: list[str] | None = None,
        state_file: str | None = None,
        actions_file: str | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.workdir = Path(workdir).resolve()
        tools_dir = Path(custom_tool_dir)
        if not tools_dir.is_absolute():
            tools_dir = (self.workdir / tools_dir).resolve()
        self.custom_tool_dir = tools_dir
        self.tool_executor = tool_executor
        self.planner = planner
        self.enabled = _bool_env("SELF_EXPANSION_ENABLED", True) if enabled is None else enabled
        self.auto_apply = _bool_env("SELF_EXPANSION_AUTO_APPLY", True) if auto_apply is None else auto_apply
        self.max_events_per_cycle = (
            _int_env("SELF_EXPANSION_MAX_EVENTS", 3, minimum=1)
            if max_events_per_cycle is None
            else max(1, int(max_events_per_cycle))
        )
        default_feedback_files = os.getenv(
            "SELF_EXPANSION_FEEDBACK_FILES",
            "logs/agent_feedback.jsonl,logs/self_heal_feedback.jsonl",
        )
        raw_feedback_files = feedback_files if feedback_files is not None else [x.strip() for x in default_feedback_files.split(",")]
        self.feedback_files = [self._resolve_under_workdir(x) for x in raw_feedback_files if x.strip()]
        self.state_file = self._resolve_under_workdir(state_file or os.getenv("SELF_EXPANSION_STATE_FILE", "logs/self_expansion_state.json"))
        self.actions_file = self._resolve_under_workdir(actions_file or os.getenv("SELF_EXPANSION_ACTIONS_FILE", "logs/self_expansion_actions.jsonl"))

    def _resolve_under_workdir(self, path_text: str) -> Path:
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = (self.workdir / candidate).resolve()
        else:
            candidate = candidate.resolve()
        try:
            candidate.relative_to(self.workdir)
        except ValueError as exc:
            raise ValueError(f"경로가 작업 디렉토리 범위를 벗어났습니다: {path_text}") from exc
        return candidate

    @staticmethod
    def _safe_json_extract(text: str) -> dict[str, Any] | None:
        raw = text.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return None
        except json.JSONDecodeError:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"files": {}}
        try:
            parsed = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                files = parsed.get("files")
                if isinstance(files, dict):
                    return parsed
        except Exception:
            pass
        return {"files": {}}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_action_log(self, payload: dict[str, Any]) -> None:
        self.actions_file.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": _utc_now(), **payload}
        with self.actions_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read_pending_feedback(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        state = self._load_state()
        files_state = state.setdefault("files", {})
        events: list[dict[str, Any]] = []
        remaining = self.max_events_per_cycle

        for path in self.feedback_files:
            if remaining <= 0:
                break
            rel = str(path.relative_to(self.workdir))
            offset = files_state.get(rel, 0)
            if not isinstance(offset, int) or offset < 0:
                offset = 0
            if not path.exists() or not path.is_file():
                files_state[rel] = 0
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if offset > len(lines):
                offset = 0
            read_count = 0
            for idx in range(offset, len(lines)):
                if remaining <= 0:
                    break
                raw_line = lines[idx].strip()
                read_count += 1
                if not raw_line:
                    remaining -= 1
                    continue
                try:
                    parsed = json.loads(raw_line)
                except json.JSONDecodeError:
                    parsed = {"event": "malformed_feedback_line", "raw": raw_line}
                if isinstance(parsed, dict):
                    parsed["_meta"] = {"source_file": rel, "line_no": idx + 1}
                    events.append(parsed)
                remaining -= 1
            files_state[rel] = offset + read_count
        return events, state

    @staticmethod
    def _is_actionable_event(event: dict[str, Any]) -> bool:
        kind = str(event.get("event", "")).strip()
        if kind == "react_feedback":
            detail = event.get("detail", {})
            if isinstance(detail, dict):
                failure_kind = str(detail.get("kind", "")).strip()
                return failure_kind in {"max_tool_rounds", "repeated_tool_call"}
            return True
        if kind in {"emergency_recovery", "guardian_report_on_exit"}:
            return True
        return False

    def _tool_list_snapshot(self) -> list[dict[str, Any]]:
        try:
            items = self.tool_executor.describe_tools()
            if isinstance(items, list):
                return items[:60]
        except Exception:
            pass
        return []

    def _load_tool_reference_snippet(self) -> str:
        candidate = self.custom_tool_dir / "add_two_numbers.py"
        if not candidate.exists():
            return ""
        text = candidate.read_text(encoding="utf-8", errors="replace")
        return text[:2600]

    def _plan_with_llm(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key or not self.model:
            return {"action": "none", "reason": "API 키 또는 모델 설정이 없습니다."}

        prompt = (
            "You are a self-expansion planner for a Python tool agent.\n"
            "Task: inspect recent failure feedback and propose exactly one safe tool code patch.\n"
            "Return JSON only with this schema:\n"
            "{\n"
            '  "action":"none|create_or_update_tool",\n'
            '  "reason":"...",\n'
            '  "tool_file":"snake_case.py",\n'
            '  "tool_name":"snake_case",\n'
            '  "code":"full python file content"\n'
            "}\n"
            "Rules:\n"
            "- Modify/create only tools/*.py.\n"
            "- Include TOOL_SPEC, version, run(), CLI flags (--tool-spec-json, --tool-input-json, --tool-context-json), __main__.\n"
            "- If feedback is insufficient, return action=none.\n\n"
            f"Current tools snapshot:\n{json.dumps(payload.get('tools', []), ensure_ascii=False)}\n\n"
            f"Recent actionable feedback:\n{json.dumps(payload.get('events', []), ensure_ascii=False)}\n\n"
            f"Reference tool snippet:\n{payload.get('reference_tool', '')}\n"
        )
        conn = http.client.HTTPSConnection("api.anthropic.com", timeout=45)
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 1400,
                "messages": [{"role": "user", "content": prompt}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            conn.request(
                "POST",
                "/v1/messages",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200:
                return {"action": "none", "reason": f"플래너 API 오류 {resp.status}"}
            try:
                data = json.loads(raw)
                blocks = data.get("content", [])
                text = "".join(
                    str(block.get("text", ""))
                    for block in blocks
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            except Exception:
                text = raw
            parsed = self._safe_json_extract(text)
            if parsed is None:
                return {"action": "none", "reason": "플래너가 JSON이 아닌 응답을 반환했습니다."}
            return parsed
        except Exception as exc:
            return {"action": "none", "reason": f"플래너 예외 발생: {exc}"}
        finally:
            conn.close()

    def _get_planner(self) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if self.planner is not None:
            return self.planner
        return self._plan_with_llm

    @staticmethod
    def _validate_tool_file_name(file_name: str) -> str:
        name = file_name.strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+\.py", name):
            raise ValueError("tool_file must match [A-Za-z0-9_]+.py")
        return name

    @staticmethod
    def _validate_tool_code_contract(code: str) -> None:
        markers = [
            "TOOL_SPEC",
            "version",
            "def run(",
            "__main__",
            "--tool-spec-json",
            "--tool-input-json",
            "--tool-context-json",
        ]
        missing = [m for m in markers if m not in code]
        if missing:
            raise ValueError("필수 도구 계약 마커가 누락되었습니다: " + ", ".join(missing))
        ast.parse(code)

    def _apply_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        action = str(plan.get("action", "none")).strip().lower()
        if action not in {"none", "create_or_update_tool"}:
            return {"changed": False, "applied": False, "error": f"지원하지 않는 action입니다: {action}"}
        if action == "none":
            return {"changed": False, "applied": False, "reason": str(plan.get("reason", ""))}
        if not self.auto_apply:
            return {"changed": False, "applied": False, "reason": "auto_apply가 비활성화되어 있습니다."}

        file_name = self._validate_tool_file_name(str(plan.get("tool_file", "")))
        code = str(plan.get("code", ""))
        if not code.strip():
            raise ValueError("create_or_update_tool action에는 code 값이 필요합니다.")
        if len(code) > 120_000:
            raise ValueError("code 길이가 너무 큽니다.")
        self._validate_tool_code_contract(code)

        target = (self.custom_tool_dir / file_name).resolve()
        try:
            target.relative_to(self.custom_tool_dir)
        except ValueError as exc:
            raise ValueError("tool_file 경로가 커스텀 도구 디렉토리 범위를 벗어났습니다.") from exc

        raw_executor = getattr(self.tool_executor, "base_executor", self.tool_executor)
        result_text, is_error = raw_executor.run_tool(
            "create_or_update_custom_tool_file",
            {"file_name": file_name, "content": code},
        )
        if is_error:
            return {"changed": False, "applied": False, "error": result_text}
        try:
            raw_executor.sync_custom_tools(force=True)
        except Exception:
            pass
        return {
            "changed": True,
            "applied": True,
            "file_name": file_name,
            "result": result_text,
        }

    def run_cycle(self, trigger: str = "", force: bool = False) -> dict[str, Any]:
        if not self.enabled and not force:
            return {"enabled": False, "processed_events": 0, "action": "none", "changed": False}

        events, state = self._read_pending_feedback()
        if not events:
            return {"enabled": self.enabled, "processed_events": 0, "action": "none", "changed": False}

        actionable = [event for event in events if self._is_actionable_event(event)]
        self._save_state(state)

        if not actionable and not force:
            result = {
                "enabled": self.enabled,
                "processed_events": len(events),
                "actionable_events": 0,
                "action": "none",
                "changed": False,
                "reason": "처리 가능한 피드백이 없습니다.",
            }
            self._append_action_log({"trigger": trigger, **result})
            return result

        payload = {
            "events": actionable[: self.max_events_per_cycle] if not force else events[: self.max_events_per_cycle],
            "tools": self._tool_list_snapshot(),
            "reference_tool": self._load_tool_reference_snippet(),
        }
        planner = self._get_planner()
        plan = planner(payload)
        if not isinstance(plan, dict):
            plan = {"action": "none", "reason": "플래너가 잘못된 payload를 반환했습니다."}

        try:
            applied = self._apply_plan(plan)
        except Exception as exc:
            applied = {
                "changed": False,
                "applied": False,
                "error": str(exc),
            }
        action_result = {
            "enabled": self.enabled,
            "processed_events": len(events),
            "actionable_events": len(actionable),
            "action": str(plan.get("action", "none")),
            "reason": str(plan.get("reason", "")),
            "changed": bool(applied.get("changed")),
            "applied": bool(applied.get("applied")),
            "result": applied,
            "plan_tool_file": str(plan.get("tool_file", "")),
            "plan_tool_name": str(plan.get("tool_name", "")),
        }
        self._append_action_log({"trigger": trigger, **action_result})
        return action_result
