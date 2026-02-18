#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


DEFAULTS = {
    "CLAUDE_MODEL": "claude-sonnet-4-5-20250929",
    "CLAUDE_MAX_TOKENS": "1024",
    "TOOL_WORKDIR": ".",
    "CUSTOM_TOOL_DIR": "tools",
    "STRICT_WORKDIR_ONLY": "1",
    "SCHEDULER_ENABLED": "1",
    "SCHEDULER_POLL_SECONDS": "30",
    "HEALTH_SERVER_ENABLED": "1",
    "HEALTH_PORT": "8080",
    "SESSION_LOG_SPLIT": "1",
}


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={values[k]}" for k in sorted(values.keys())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ask(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    return raw


def run_setup_wizard(
    *,
    env_path: str = ".env",
    non_interactive: bool = False,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(env_path)
    values = _read_env(path)
    for key, val in DEFAULTS.items():
        values.setdefault(key, val)

    updates = updates or {}

    if non_interactive:
        for key, val in updates.items():
            if key and val is not None:
                values[str(key)] = str(val)
        _write_env(path, values)
        return {"ok": True, "path": str(path.resolve()), "mode": "non_interactive", "count": len(values)}

    api_key_default = values.get("ANTHROPIC_API_KEY", "")
    api_key = _ask("ANTHROPIC_API_KEY 입력(없으면 비워둠)", api_key_default)
    if api_key:
        values["ANTHROPIC_API_KEY"] = api_key

    values["CLAUDE_MODEL"] = _ask("CLAUDE_MODEL", values.get("CLAUDE_MODEL", DEFAULTS["CLAUDE_MODEL"]))
    values["CLAUDE_MAX_TOKENS"] = _ask(
        "CLAUDE_MAX_TOKENS",
        values.get("CLAUDE_MAX_TOKENS", DEFAULTS["CLAUDE_MAX_TOKENS"]),
    )
    values["TOOL_WORKDIR"] = _ask("TOOL_WORKDIR", values.get("TOOL_WORKDIR", DEFAULTS["TOOL_WORKDIR"]))
    values["CUSTOM_TOOL_DIR"] = _ask("CUSTOM_TOOL_DIR", values.get("CUSTOM_TOOL_DIR", DEFAULTS["CUSTOM_TOOL_DIR"]))
    values["STRICT_WORKDIR_ONLY"] = _ask(
        "STRICT_WORKDIR_ONLY (1/0)",
        values.get("STRICT_WORKDIR_ONLY", DEFAULTS["STRICT_WORKDIR_ONLY"]),
    )
    values["SCHEDULER_ENABLED"] = _ask(
        "SCHEDULER_ENABLED (1/0)",
        values.get("SCHEDULER_ENABLED", DEFAULTS["SCHEDULER_ENABLED"]),
    )
    values["SCHEDULER_POLL_SECONDS"] = _ask(
        "SCHEDULER_POLL_SECONDS",
        values.get("SCHEDULER_POLL_SECONDS", DEFAULTS["SCHEDULER_POLL_SECONDS"]),
    )

    for key, val in updates.items():
        if key and val is not None:
            values[str(key)] = str(val)

    _write_env(path, values)
    return {"ok": True, "path": str(path.resolve()), "mode": "interactive", "count": len(values)}


def main() -> int:
    parser = argparse.ArgumentParser(description="BoramClaw setup wizard")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    updates: dict[str, str] = {}
    if args.api_key.strip():
        updates["ANTHROPIC_API_KEY"] = args.api_key.strip()
    if args.model.strip():
        updates["CLAUDE_MODEL"] = args.model.strip()

    result = run_setup_wizard(
        env_path=args.env,
        non_interactive=bool(args.non_interactive),
        updates=updates,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
