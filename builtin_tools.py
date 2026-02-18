from __future__ import annotations


class BuiltinTools:
    """
    Minimal built-in tool metadata helper.
    """

    def __init__(self, workdir: str, strict_mode: bool) -> None:
        self.workdir = workdir
        self.strict_mode = strict_mode

    @staticmethod
    def default_permissions() -> dict[str, str]:
        return {
            "run_shell": "prompt",
            "delete_custom_tool_file": "prompt",
            "write_file": "allow",
            "save_text_file": "allow",
        }
