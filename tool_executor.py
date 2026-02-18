from __future__ import annotations

from typing import Any, Callable


class PolicyToolExecutor:
    """
    Permission and approval gate wrapper around an existing tool executor.

    Permission levels:
    - allow: execute directly
    - prompt: execute only if approval callback returns True
    - deny: block execution
    """

    def __init__(
        self,
        base_executor: Any,
        permissions: dict[str, str] | None = None,
        approval_callback: Callable[[str, dict[str, Any]], bool] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.base_executor = base_executor
        self.permissions = {k: str(v).strip().lower() for k, v in (permissions or {}).items()}
        self.approval_callback = approval_callback
        self.dry_run = dry_run

    def set_permissions(self, permissions: dict[str, str]) -> None:
        self.permissions = {k: str(v).strip().lower() for k, v in permissions.items()}

    def run_tool(self, name: str, input_data: dict[str, Any]) -> tuple[str, bool]:
        permission = self.permissions.get(name, "allow")
        if permission == "deny":
            return f'{{"error":"정책에 의해 도구 {name} 실행이 차단되었습니다."}}', True
        if permission == "prompt":
            if self.approval_callback is None:
                return f'{{"error":"도구 {name} 실행을 위한 승인 콜백이 필요합니다."}}', True
            if not self.approval_callback(name, input_data):
                return '{"error":"사용자가 도구 실행을 거부했습니다."}', True
        if self.dry_run:
            return f'{{"dry_run":true,"tool":"{name}","input":{input_data!r}}}', False
        return self.base_executor.run_tool(name, input_data)

    def __getattr__(self, item: str) -> Any:
        return getattr(self.base_executor, item)
