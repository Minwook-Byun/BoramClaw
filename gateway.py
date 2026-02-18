from __future__ import annotations

import http.client
import json
import threading
import time
from typing import Any, Callable


API_HOST = "api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOOL_ROUNDS = 12
MAX_API_RETRIES = 3


class RequestQueue:
    """Explicit lane queue for serialized request execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def run(self, task: Callable[[], str]) -> str:
        with self._lock:
            return task()


class ClaudeChat:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        system_prompt: str = "",
        force_tool_use: bool = False,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.force_tool_use = force_tool_use
        self.conn = http.client.HTTPSConnection(API_HOST, timeout=60)
        self.history: list[dict[str, Any]] = []
        self.request_queue = RequestQueue()
        self._total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "requests": 0}
        self._pending_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "requests": 0}

    def reset_session(self, summary: str = "") -> None:
        self.history = []
        note = summary.strip()
        if note:
            self.history.append(
                {
                    "role": "assistant",
                    "content": f"Previous session summary (tooling changed):\n{note}",
                }
            )

    def _perform_http_request(self, body: bytes) -> tuple[int, bytes]:
        self.conn.request(
            "POST",
            "/v1/messages",
            body=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
        )
        response = self.conn.getresponse()
        raw = response.read()
        return int(response.status), raw

    def _request(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
            "system": self.system_prompt,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = {"type": "any"} if self.force_tool_use else {"type": "auto"}

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        raw: bytes = b""
        status = 0
        for attempt in range(MAX_API_RETRIES):
            try:
                status, raw = self._perform_http_request(body)
                if status == 200:
                    break
                retryable = status in {429, 500, 502, 503, 504}
                if retryable and attempt < (MAX_API_RETRIES - 1):
                    time.sleep(min(2.0, 0.5 * (2**attempt)))
                    continue
                try:
                    message = json.loads(raw.decode("utf-8")).get("error", {}).get("message", "")
                except json.JSONDecodeError:
                    message = ""
                if not message:
                    message = raw.decode("utf-8", errors="replace")
                raise RuntimeError(f"API 오류 {status}: {message}")
            except (http.client.HTTPException, OSError, TimeoutError) as exc:
                if attempt < (MAX_API_RETRIES - 1):
                    time.sleep(min(2.0, 0.5 * (2**attempt)))
                    continue
                raise RuntimeError(f"API 연결 오류: {exc}") from exc

        if status != 200:
            try:
                message = json.loads(raw.decode("utf-8")).get("error", {}).get("message", "")
            except json.JSONDecodeError:
                message = raw.decode("utf-8", errors="replace")
            raise RuntimeError(f"API 오류 {status}: {message}")
        data = json.loads(raw.decode("utf-8"))
        usage = data.get("usage")
        if isinstance(usage, dict):
            in_tok = int(usage.get("input_tokens", 0) or 0)
            out_tok = int(usage.get("output_tokens", 0) or 0)
        else:
            in_tok = 0
            out_tok = 0
        self._pending_usage["input_tokens"] += in_tok
        self._pending_usage["output_tokens"] += out_tok
        self._pending_usage["requests"] += 1
        self._total_usage["input_tokens"] += in_tok
        self._total_usage["output_tokens"] += out_tok
        self._total_usage["requests"] += 1
        return data

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text", "")))
        return "".join(texts).strip()

    def ask(
        self,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        tool_runner: Callable[[str, dict[str, Any]], tuple[str, bool]] | None = None,
        on_tool_event: Callable[[str, dict[str, Any], str, bool], None] | None = None,
    ) -> str:
        def _task() -> str:
            self._pending_usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0}
            self.history.append({"role": "user", "content": user_message})
            if not tools or tool_runner is None:
                response = self._request(self.history)
                content = response.get("content", [])
                self.history.append({"role": "assistant", "content": content})
                return self._extract_text(content)

            repeated_calls: dict[str, int] = {}
            for _ in range(MAX_TOOL_ROUNDS):
                response = self._request(self.history, tools=tools)
                assistant_content = response.get("content", [])
                self.history.append({"role": "assistant", "content": assistant_content})
                tool_uses = [
                    block for block in assistant_content if isinstance(block, dict) and block.get("type") == "tool_use"
                ]
                if not tool_uses:
                    return self._extract_text(assistant_content)
                for tool_use in tool_uses:
                    tool_id = str(tool_use.get("id", ""))
                    tool_name = str(tool_use.get("name", ""))
                    tool_input = tool_use.get("input")
                    if not isinstance(tool_input, dict):
                        tool_input = {}
                    signature = json.dumps(
                        {"name": tool_name, "input": tool_input},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    repeated_calls[signature] = repeated_calls.get(signature, 0) + 1
                    if repeated_calls[signature] >= 4:
                        message = (
                            "도구 호출이 같은 형태로 반복되어 중단했습니다. "
                            "요청을 더 구체화하거나 /tool 명령으로 직접 실행해 주세요."
                        )
                        if on_tool_event is not None:
                            on_tool_event(
                                "react_feedback",
                                {
                                    "kind": "repeated_tool_call",
                                    "tool_name": tool_name,
                                    "tool_input": tool_input,
                                    "repeat_count": repeated_calls[signature],
                                },
                                message,
                                True,
                            )
                        return message
                    result_text, is_error = tool_runner(tool_name, tool_input)
                    if on_tool_event is not None:
                        on_tool_event(tool_name, tool_input, result_text, is_error)
                    if not tool_id:
                        continue
                    self.history.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": result_text,
                                    "is_error": is_error,
                                }
                            ],
                        }
                    )
            message = "도구 호출 루프가 제한 횟수를 초과해 중단되었습니다. /tool 명령으로 직접 실행해 주세요."
            if on_tool_event is not None:
                on_tool_event(
                    "react_feedback",
                    {
                        "kind": "max_tool_rounds",
                        "max_rounds": MAX_TOOL_ROUNDS,
                    },
                    message,
                    True,
                )
            return message

        return self.request_queue.run(_task)

    def consume_pending_usage(self) -> dict[str, int]:
        usage = dict(self._pending_usage)
        self._pending_usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0}
        return usage

    def get_total_usage(self) -> dict[str, int]:
        return dict(self._total_usage)
