from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable


class JobScheduler:
    def __init__(
        self,
        poll_seconds: int,
        tool_executor: Any,
        on_job_run: Callable[[dict[str, Any]], None] | None = None,
        on_heartbeat: Callable[[dict[str, Any]], None] | None = None,
        pending_tasks_file: str = "tasks/pending.txt",
    ) -> None:
        self.poll_seconds = max(5, int(poll_seconds))
        self.tool_executor = tool_executor
        self.on_job_run = on_job_run
        self.on_heartbeat = on_heartbeat
        self.pending_tasks_file = pending_tasks_file
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="job-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                executions = self.tool_executor.run_due_scheduled_jobs()
                if self.on_job_run is not None:
                    for item in executions:
                        self.on_job_run(item)
            except Exception as exc:
                if self.on_job_run is not None:
                    self.on_job_run({"status": "error", "error": str(exc)})
            self._heartbeat()
            self._stop.wait(self.poll_seconds)

    def _heartbeat(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "event": "heartbeat",
            "ts": now,
            "message": f"Checking pending tasks at {now}",
        }
        pending_file = Path(self.pending_tasks_file)
        if pending_file.exists():
            tasks = [line.strip() for line in pending_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            payload["pending_count"] = len(tasks)
            payload["pending_tasks"] = tasks[:20]
            execution = self._run_pending_tasks(tasks)
            payload.update(execution)
            failed_lines = execution.get("failed_lines", [])
            if isinstance(failed_lines, list) and failed_lines:
                pending_file.parent.mkdir(parents=True, exist_ok=True)
                pending_file.write_text("\n".join(str(x) for x in failed_lines) + "\n", encoding="utf-8")
            else:
                try:
                    pending_file.unlink()
                except OSError:
                    pass
        else:
            payload["pending_count"] = 0
        if self.on_heartbeat is not None:
            self.on_heartbeat(payload)

    def _parse_pending_line(self, line: str) -> tuple[str, dict[str, Any]]:
        raw = line.strip()
        if not raw:
            raise ValueError("empty pending task line")
        # JSON format: {"tool":"name","input":{...}}
        if raw.startswith("{") and raw.endswith("}"):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("pending task JSON must be an object")
            tool_name = str(parsed.get("tool") or parsed.get("tool_name") or "").strip()
            tool_input = parsed.get("input") if isinstance(parsed.get("input"), dict) else {}
            if not tool_name:
                raise ValueError("pending task JSON requires 'tool' or 'tool_name'")
            return tool_name, dict(tool_input)
        # Pipe format: tool_name|{\"k\":\"v\"}
        if "|" in raw:
            name_part, payload_part = raw.split("|", 1)
            tool_name = name_part.strip()
            if not tool_name:
                raise ValueError("pending task tool_name is empty")
            payload_part = payload_part.strip()
            tool_input: dict[str, Any] = {}
            if payload_part:
                parsed = json.loads(payload_part)
                if not isinstance(parsed, dict):
                    raise ValueError("pending task payload must be JSON object")
                tool_input = dict(parsed)
            return tool_name, tool_input
        # Plain text fallback
        return "process_pending_task", {"task": raw}

    def _run_pending_tasks(self, tasks: list[str]) -> dict[str, Any]:
        executed = 0
        ok_count = 0
        error_count = 0
        failed_lines: list[str] = []
        results: list[dict[str, Any]] = []
        for line in tasks[:100]:
            try:
                tool_name, tool_input = self._parse_pending_line(line)
                result_text, is_error = self.tool_executor.run_tool(tool_name, tool_input)
                executed += 1
                if is_error:
                    error_count += 1
                    failed_lines.append(line)
                else:
                    ok_count += 1
                results.append(
                    {
                        "tool": tool_name,
                        "ok": not bool(is_error),
                        "result_preview": str(result_text)[:200],
                    }
                )
            except Exception as exc:
                error_count += 1
                failed_lines.append(line)
                results.append(
                    {
                        "tool": "",
                        "ok": False,
                        "error": str(exc),
                    }
                )
        return {
            "pending_executed": executed,
            "pending_ok": ok_count,
            "pending_error": error_count,
            "pending_results": results[:20],
            "failed_lines": failed_lines,
        }
