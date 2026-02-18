from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


def _read_dotenv_values(dotenv_path: str = ".env") -> dict[str, str]:
    path = Path(dotenv_path)
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv(dotenv_path: str = ".env", exclude_keys: set[str] | None = None) -> None:
    path = Path(dotenv_path)
    if not path.exists():
        return
    excluded = exclude_keys or set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in excluded:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


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


def _resolve_api_key(
    env_key: str,
    keychain_key: str,
    dotenv_key: str,
    allow_plaintext_api_key: bool,
) -> tuple[str, str]:
    env_val = env_key.strip()
    if env_val:
        return env_val, "env"
    keychain_val = keychain_key.strip()
    if keychain_val:
        return keychain_val, "keychain"
    if allow_plaintext_api_key:
        dotenv_val = dotenv_key.strip()
        if dotenv_val:
            return dotenv_val, "dotenv"
    return "", "missing"


@dataclass
class BoramClawConfig:
    anthropic_api_key: str
    claude_model: str
    claude_max_tokens: int
    chat_log_file: str
    schedule_file: str
    tool_workdir: str
    tool_timeout_seconds: int
    custom_tool_dir: str
    strict_workdir_only: bool
    scheduler_enabled: bool
    scheduler_poll_seconds: int
    agent_mode: str
    claude_system_prompt: str
    chat_log_encryption_key: str
    force_tool_use: bool
    debug: bool
    dry_run: bool
    tool_permissions_json: str
    health_server_enabled: bool
    health_port: int
    check_dependencies_on_start: bool
    session_log_split: bool
    log_base_dir: str
    keychain_service_name: str
    keychain_account_name: str
    allow_plaintext_api_key: bool = False
    api_key_source: str = "unknown"

    @classmethod
    def from_env(cls) -> "BoramClawConfig":
        dotenv_values = _read_dotenv_values(".env")
        allow_plaintext_api_key = _bool_env("ALLOW_PLAINTEXT_API_KEY", False)
        load_dotenv(
            ".env",
            exclude_keys=(set() if allow_plaintext_api_key else {"ANTHROPIC_API_KEY"}),
        )
        keychain_service = (os.getenv("KEYCHAIN_SERVICE_NAME") or "BoramClaw").strip()
        keychain_account = (os.getenv("KEYCHAIN_ACCOUNT_NAME") or "anthropic_api_key").strip()
        keychain_value = _load_key_from_keychain(service=keychain_service, account=keychain_account)
        resolved_key, key_source = _resolve_api_key(
            env_key=(os.getenv("ANTHROPIC_API_KEY") or "").strip(),
            keychain_key=keychain_value,
            dotenv_key=(dotenv_values.get("ANTHROPIC_API_KEY") or "").strip(),
            allow_plaintext_api_key=allow_plaintext_api_key,
        )
        return cls(
            anthropic_api_key=resolved_key,
            claude_model=(os.getenv("CLAUDE_MODEL") or "claude-sonnet-4-5-20250929").strip(),
            claude_max_tokens=_int_env("CLAUDE_MAX_TOKENS", 1024, minimum=1),
            chat_log_file=(os.getenv("CHAT_LOG_FILE") or "logs/chat_log.jsonl").strip(),
            schedule_file=(os.getenv("SCHEDULE_FILE") or "schedules/jobs.json").strip(),
            tool_workdir=(os.getenv("TOOL_WORKDIR") or ".").strip(),
            tool_timeout_seconds=_int_env("TOOL_TIMEOUT_SECONDS", 300, minimum=1),
            custom_tool_dir=(os.getenv("CUSTOM_TOOL_DIR") or "tools").strip(),
            strict_workdir_only=_bool_env("STRICT_WORKDIR_ONLY", True),
            scheduler_enabled=_bool_env("SCHEDULER_ENABLED", True),
            scheduler_poll_seconds=_int_env("SCHEDULER_POLL_SECONDS", 30, minimum=5),
            agent_mode=(os.getenv("AGENT_MODE") or "interactive").strip().lower(),
            claude_system_prompt=(os.getenv("CLAUDE_SYSTEM_PROMPT") or "").strip(),
            chat_log_encryption_key=(os.getenv("CHAT_LOG_ENCRYPTION_KEY") or "").strip(),
            force_tool_use=_bool_env("FORCE_TOOL_USE", False),
            debug=_bool_env("DEBUG", False),
            dry_run=_bool_env("DRY_RUN", False),
            tool_permissions_json=(os.getenv("TOOL_PERMISSIONS_JSON") or "").strip(),
            health_server_enabled=_bool_env("HEALTH_SERVER_ENABLED", True),
            health_port=_int_env("HEALTH_PORT", 8080, minimum=1),
            check_dependencies_on_start=_bool_env("CHECK_DEPENDENCIES_ON_START", False),
            session_log_split=_bool_env("SESSION_LOG_SPLIT", False),
            log_base_dir=(os.getenv("LOG_BASE_DIR") or "logs/sessions").strip(),
            keychain_service_name=keychain_service,
            keychain_account_name=keychain_account,
            allow_plaintext_api_key=allow_plaintext_api_key,
            api_key_source=key_source,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY 값이 필요합니다.")
        elif not self.anthropic_api_key.startswith("sk-ant-"):
            errors.append("ANTHROPIC_API_KEY는 'sk-ant-'로 시작해야 합니다.")

        valid_markers = ("claude-sonnet", "claude-opus", "claude-haiku")
        if not any(marker in self.claude_model for marker in valid_markers):
            errors.append("CLAUDE_MODEL에는 claude-sonnet, claude-opus, claude-haiku 중 하나가 포함되어야 합니다.")

        if self.tool_timeout_seconds <= 0:
            errors.append("TOOL_TIMEOUT_SECONDS는 0보다 커야 합니다.")
        if self.scheduler_poll_seconds < 5:
            errors.append("SCHEDULER_POLL_SECONDS는 5 이상이어야 합니다.")
        if self.health_port <= 0 or self.health_port > 65535:
            errors.append("HEALTH_PORT는 1~65535 범위여야 합니다.")
        if self.agent_mode not in {"interactive", "daemon"}:
            errors.append("AGENT_MODE는 'interactive' 또는 'daemon'이어야 합니다.")

        workdir = Path(self.tool_workdir).expanduser()
        if not workdir.exists():
            errors.append(f"TOOL_WORKDIR 경로가 존재하지 않습니다: {workdir}")
        elif not workdir.is_dir():
            errors.append(f"TOOL_WORKDIR가 디렉토리가 아닙니다: {workdir}")

        custom_tool_dir = Path(self.custom_tool_dir)
        if not custom_tool_dir.is_absolute():
            custom_tool_dir = workdir / custom_tool_dir
        if not custom_tool_dir.exists():
            errors.append(f"CUSTOM_TOOL_DIR 경로가 존재하지 않습니다: {custom_tool_dir}")
        elif not custom_tool_dir.is_dir():
            errors.append(f"CUSTOM_TOOL_DIR가 디렉토리가 아닙니다: {custom_tool_dir}")

        chat_log_path = Path(self.chat_log_file)
        if not chat_log_path.is_absolute():
            chat_log_path = workdir / chat_log_path
        chat_parent = chat_log_path.parent
        try:
            chat_parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            errors.append(f"로그 디렉토리를 생성할 수 없습니다: {chat_parent}")
        if not os.access(chat_parent, os.W_OK):
            errors.append(f"로그 디렉토리에 쓰기 권한이 없습니다: {chat_parent}")

        if self.session_log_split:
            base_dir = Path(self.log_base_dir)
            if not base_dir.is_absolute():
                base_dir = workdir / base_dir
            try:
                base_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                errors.append(f"LOG_BASE_DIR를 생성할 수 없습니다: {base_dir}")

        return errors

    def permissions_map(self) -> dict[str, str]:
        if not self.tool_permissions_json:
            return {}
        try:
            parsed = json.loads(self.tool_permissions_json)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, value in parsed.items():
            if not isinstance(key, str):
                continue
            if not isinstance(value, str):
                continue
            mode = value.strip().lower()
            if mode not in {"allow", "prompt", "deny"}:
                continue
            normalized[key.strip()] = mode
        return normalized

    def as_dict(self) -> dict[str, Any]:
        return {
            "claude_model": self.claude_model,
            "claude_max_tokens": self.claude_max_tokens,
            "chat_log_file": self.chat_log_file,
            "schedule_file": self.schedule_file,
            "tool_workdir": self.tool_workdir,
            "tool_timeout_seconds": self.tool_timeout_seconds,
            "custom_tool_dir": self.custom_tool_dir,
            "strict_workdir_only": self.strict_workdir_only,
            "scheduler_enabled": self.scheduler_enabled,
            "scheduler_poll_seconds": self.scheduler_poll_seconds,
            "agent_mode": self.agent_mode,
            "force_tool_use": self.force_tool_use,
            "debug": self.debug,
            "dry_run": self.dry_run,
            "health_server_enabled": self.health_server_enabled,
            "health_port": self.health_port,
            "check_dependencies_on_start": self.check_dependencies_on_start,
            "session_log_split": self.session_log_split,
            "log_base_dir": self.log_base_dir,
            "allow_plaintext_api_key": self.allow_plaintext_api_key,
            "api_key_source": self.api_key_source,
        }


def _load_key_from_keychain(service: str, account: str) -> str:
    try:
        from keychain_helper import load_api_key
    except Exception:
        return ""
    try:
        return load_api_key(service=service, account=account).strip()
    except Exception:
        return ""
