#!/usr/bin/env python3
from __future__ import annotations

import base64
import argparse
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import logging
from typing import Any, Callable
from uuid import uuid4
from runtime_commands import (
    _bool_env_local,
    _float_env_local,
    format_memory_query_result,
    format_permissions_map,
    format_reflexion_records,
    format_tool_list,
    format_user_output,
    format_workday_recap,
    is_schedule_list_request,
    is_tool_list_request,
    parse_arxiv_quick_request,
    parse_context_command,
    parse_delegate_command,
    parse_feedback_command,
    parse_memory_command,
    parse_reflexion_command,
    parse_schedule_arxiv_command,
    parse_set_permission_command,
    parse_today_command,
    parse_tool_command,
    parse_tool_only_mode_command,
    parse_week_command,
    summarize_for_memory,
)


API_HOST = "api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TOOL_TIMEOUT_SECONDS = 300
MAX_TOOL_TIMEOUT_SECONDS = 300
DEFAULT_SCHEDULER_POLL_SECONDS = 30
MAX_TOOL_ROUNDS = 8
MAX_TOOL_OUTPUT_CHARS = 4000

DEFAULT_SYSTEM_PROMPT = (
    "당신은 파이썬 코드를 스스로 작성·실행해 기능을 확장하는 자율 AI 에이전트입니다. "
    "모든 도구는 tools/ 하위의 개별 .py 파일이며 런타임에 파일시스템에서 동적으로 발견합니다. "
    "도구 우선 원칙을 따르세요: 직접 답변보다 먼저 기존 도구를 우선 사용합니다. "
    "새 도구 생성/수정은 사용자가 명시적으로 요청한 경우에만 수행하세요. "
    "main.py는 tools를 직접 import하지 않으며, 커스텀 도구는 독립 subprocess로 실행됩니다. "
    "커스텀 도구는 반드시 __main__ 실행 블록과 argparse/sys.argv 기반 인자 파싱을 제공해야 합니다. "
    "새 도구를 만들 때는 read_text_file로 기존 tools 예시를 먼저 읽고 입력/출력 규약을 맞춥니다. "
    "코드 생성 후에는 save_text_file로 tools/ 하위에만 저장합니다. "
    "list_custom_tools, tool_registry_status, create_or_update_custom_tool_file, delete_custom_tool_file로 도구를 관리합니다. "
    "결과를 지어내지 말고 도구 출력만 근거로 응답하세요. "
    "사용자와의 모든 대화는 한국어로 진행하세요. "
    "커스텀 도구가 존재하는 경우 run_shell로 우회 실행하지 말고 해당 도구를 직접 호출하세요."
)

TOOL_SUBPROCESS_WRAPPER = r"""
import json
import os
from pathlib import Path
import runpy
import sys


def _resolve_for_audit(path_value):
    raw = None
    if isinstance(path_value, bytes):
        try:
            raw = path_value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    elif isinstance(path_value, str):
        raw = path_value
    elif isinstance(path_value, os.PathLike):
        raw = os.fspath(path_value)
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _is_write_intent_open(args):
    mode = ""
    if len(args) >= 2 and isinstance(args[1], str):
        mode = args[1]
    if any(flag in mode for flag in ("w", "a", "x", "+")):
        return True
    if len(args) >= 3 and isinstance(args[2], int):
        flags = args[2]
        write_flags = (
            os.O_WRONLY
            | os.O_RDWR
            | os.O_APPEND
            | os.O_CREAT
            | os.O_TRUNC
        )
        return bool(flags & write_flags)
    return False


strict = os.getenv("STRICT_WORKDIR_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
strict_no_network = os.getenv("STRICT_NO_NETWORK", "1").strip().lower() in {"1", "true", "yes", "on"}
root_text = os.getenv("TOOL_WORKDIR_ROOT", "").strip()
root = Path(root_text).resolve() if root_text else None

if strict and strict_no_network:
    import socket as _socket

    class _BlockedSocket(_socket.socket):
        def connect(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise PermissionError(
                "Blocked by strict_workdir_only in tool subprocess: network access is not allowed."
            )

        def connect_ex(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise PermissionError(
                "Blocked by strict_workdir_only in tool subprocess: network access is not allowed."
            )

    def _blocked_create_connection(*args, **kwargs):  # noqa: ANN002,ANN003
        raise PermissionError(
            "Blocked by strict_workdir_only in tool subprocess: network access is not allowed."
        )

    _socket.socket = _BlockedSocket
    _socket.create_connection = _blocked_create_connection

if strict and root is not None:
    def _enforce_path_under_root(path_value, action):
        resolved = _resolve_for_audit(path_value)
        if resolved is None:
            return
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise PermissionError(
                f"Blocked by strict_workdir_only in tool subprocess: {action} outside workdir ({resolved})"
            ) from exc

    def _audit_hook(event, args):
        if event == "subprocess.Popen":
            raise PermissionError("Blocked by strict_workdir_only in tool subprocess: subprocess is not allowed.")
        if strict_no_network and event in {"socket.connect", "socket.getaddrinfo"}:
            raise PermissionError(
                "Blocked by strict_workdir_only in tool subprocess: network access is not allowed."
            )
        if event == "open":
            if _is_write_intent_open(args):
                path_value = args[0] if args else None
                _enforce_path_under_root(path_value, "file write")
            return
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime"}:
            path_value = args[0] if args else None
            _enforce_path_under_root(path_value, event)
            return
        if event in {"os.rename", "os.replace", "os.link", "os.symlink"}:
            src = args[0] if len(args) > 0 else None
            dst = args[1] if len(args) > 1 else None
            _enforce_path_under_root(src, event)
            _enforce_path_under_root(dst, event)
            return

    sys.addaudithook(_audit_hook)

tool_file = os.environ["AGENT_TOOL_FILE"]
tool_argv_raw = os.environ.get("AGENT_TOOL_ARGV_JSON", "[]")
try:
    tool_argv = json.loads(tool_argv_raw)
except Exception:
    tool_argv = []
if not isinstance(tool_argv, list):
    tool_argv = []
sys.argv = [tool_file] + [str(item) for item in tool_argv]
runpy.run_path(tool_file, run_name="__main__")
"""


def handle_daemon_service_command(*, install: bool, uninstall: bool, dry_run: bool) -> bool:
    if not install and not uninstall:
        return False

    import platform
    from install_daemon import install_linux, install_macos, uninstall_linux, uninstall_macos

    system = platform.system()
    if install:
        if system == "Darwin":
            install_macos(dry_run=dry_run)
            return True
        if system == "Linux":
            install_linux(dry_run=dry_run)
            return True
        raise RuntimeError(f"지원하지 않는 플랫폼입니다: {system}")

    if system == "Darwin":
        uninstall_macos(dry_run=dry_run)
        return True
    if system == "Linux":
        uninstall_linux(dry_run=dry_run)
        return True
    raise RuntimeError(f"지원하지 않는 플랫폼입니다: {system}")


def redact_sensitive_text(text: str) -> str:
    redacted = text
    patterns = [
        ("sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{16,}", "[REDACTED_API_KEY]"),
        ("(?i)(api[_-]?key\\s*[:=]\\s*)([^\\s,;]+)", "\\1[REDACTED]"),
        ("(?i)(authorization\\s*:\\s*bearer\\s+)([^\\s,;]+)", "\\1[REDACTED]"),
        ("(?i)(password\\s*[:=]\\s*)([^\\s,;]+)", "\\1[REDACTED]"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def _derive_keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    chunks = bytearray()
    counter = 0
    while len(chunks) < size:
        block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
        chunks.extend(block)
        counter += 1
    return bytes(chunks[:size])


def encrypt_text(plain: str, key_text: str) -> str:
    if not key_text:
        redacted = redact_sensitive_text(plain).encode("utf-8")
        digest = hashlib.sha256(redacted).hexdigest()
        return f"hash:v1:{digest}"

    key = hashlib.sha256(key_text.encode("utf-8")).digest()
    nonce = os.urandom(12)
    data = redact_sensitive_text(plain).encode("utf-8")
    stream = _derive_keystream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    token = base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")
    return f"enc:v1:{token}"


def safe_log_payload(text: str, encryption_key: str) -> str:
    return encrypt_text(text, encryption_key)


def load_dotenv(dotenv_path: str = ".env") -> None:
    path = Path(dotenv_path)
    if not path.exists():
        return

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

        os.environ.setdefault(key, value)


class ChatLogger:
    def __init__(self, log_file: str) -> None:
        self.log_path = Path(log_file)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.turn = 0
        self.lock = threading.Lock()

    def log(self, event: str, payload: str, **extra: object) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "turn": self.turn,
            "event": event,
            "payload": payload,
        }
        if extra:
            record.update(extra)
        try:
            with self.lock:
                with self.log_path.open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def next_turn(self) -> None:
        self.turn += 1


class ToolExecutor:
    _audit_hook_lock = threading.Lock()
    _audit_hook_installed = False
    _audit_root: Path | None = None
    _audit_context = threading.local()

    @classmethod
    def _set_audit_allow_subprocess(cls, value: bool) -> None:
        setattr(cls._audit_context, "allow_subprocess", value)

    @classmethod
    def _resolve_for_audit(cls, path_value: Any) -> Path | None:
        raw: str | None = None
        if isinstance(path_value, bytes):
            try:
                raw = path_value.decode("utf-8", errors="ignore")
            except Exception:
                return None
        elif isinstance(path_value, str):
            raw = path_value
        elif isinstance(path_value, os.PathLike):
            raw = os.fspath(path_value)
        if raw is None or raw == "":
            return None
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    @classmethod
    def _is_write_intent_open(cls, args: tuple[Any, ...]) -> bool:
        mode = ""
        if len(args) >= 2 and isinstance(args[1], str):
            mode = args[1]
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            return True
        if len(args) >= 3 and isinstance(args[2], int):
            flags = args[2]
            write_flags = (
                os.O_WRONLY
                | os.O_RDWR
                | os.O_APPEND
                | os.O_CREAT
                | os.O_TRUNC
            )
            return bool(flags & write_flags)
        return False

    @classmethod
    def _enforce_path_under_root(cls, path_value: Any, action: str) -> None:
        root = cls._audit_root
        if root is None:
            return
        resolved = cls._resolve_for_audit(path_value)
        if resolved is None:
            return
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise PermissionError(
                f"Blocked by strict_workdir_only: {action} outside workdir is not allowed ({resolved})."
            ) from exc

    @classmethod
    def _ensure_audit_hook(cls, workdir: Path) -> None:
        with cls._audit_hook_lock:
            if cls._audit_hook_installed:
                if cls._audit_root is not None and workdir != cls._audit_root:
                    try:
                        workdir.relative_to(cls._audit_root)
                    except ValueError as exc:
                        raise RuntimeError(
                            "strict_workdir_only requires a single shared workdir root per process."
                        ) from exc
                return

            cls._audit_root = workdir

            def audit_hook(event: str, args: tuple[Any, ...]) -> None:
                if event == "subprocess.Popen":
                    if not getattr(cls._audit_context, "allow_subprocess", False):
                        raise PermissionError(
                            "Blocked by strict_workdir_only: subprocess from tool runtime is not allowed."
                        )
                    return

                if event == "open":
                    if cls._is_write_intent_open(args):
                        path_value = args[0] if args else None
                        cls._enforce_path_under_root(path_value, "file write")
                    return

                if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime"}:
                    path_value = args[0] if args else None
                    cls._enforce_path_under_root(path_value, event)
                    return

                if event in {"os.rename", "os.replace", "os.link", "os.symlink"}:
                    src = args[0] if len(args) > 0 else None
                    dst = args[1] if len(args) > 1 else None
                    cls._enforce_path_under_root(src, event)
                    cls._enforce_path_under_root(dst, event)
                    return

            sys.addaudithook(audit_hook)
            cls._audit_hook_installed = True

    def __init__(
        self,
        workdir: str,
        default_timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
        max_output_chars: int = MAX_TOOL_OUTPUT_CHARS,
        custom_tool_dir: str = "tools",
        schedule_file: str = "schedules/jobs.json",
        strict_workdir_only: bool = True,
    ) -> None:
        self.workdir = Path(workdir).resolve()
        self.default_timeout_seconds = max(1, default_timeout_seconds)
        self.max_output_chars = max(400, max_output_chars)
        self.custom_tool_dir = self._resolve_custom_tool_dir(custom_tool_dir)
        self.schedule_file = self._resolve_schedule_file(schedule_file)
        self.strict_workdir_only = strict_workdir_only
        if self.strict_workdir_only:
            self._ensure_audit_hook(self.workdir)
        self.custom_tools_lock = threading.Lock()
        self.last_filesystem_scan_at: str | None = None
        self.custom_file_state: dict[str, int] = {}
        self.custom_tool_spec_map: dict[str, dict[str, Any]] = {}
        self.custom_tool_files: dict[str, str] = {}
        self.custom_tool_sources: dict[str, Path] = {}
        self.custom_tool_file_to_name: dict[str, str] = {}
        self.custom_tool_error_by_file: dict[str, str] = {}
        self.load_errors: list[str] = []
        self.tool_schema_selection_cache: dict[str, list[str]] = {}
        self.tool_schema_cache_hits = 0
        self.tool_schema_cache_misses = 0
        self.last_tool_schema_report: dict[str, Any] = {}
        self.jobs_lock = threading.Lock()
        self.jobs: list[dict[str, Any]] = []
        self._builtin_tool_names = {
            "list_files",
            "read_file",
            "read_text_file",
            "write_file",
            "save_text_file",
            "run_shell",
            "run_python",
            "list_custom_tools",
            "reload_custom_tools",
            "tool_registry_status",
            "create_or_update_custom_tool_file",
            "delete_custom_tool_file",
            "schedule_daily_tool",
            "list_scheduled_jobs",
            "delete_scheduled_job",
            "run_due_scheduled_jobs",
        }
        self.sync_custom_tools(force=True)
        self._load_jobs()

    def _resolve_custom_tool_dir(self, custom_tool_dir: str) -> Path:
        candidate = Path(custom_tool_dir)
        if not candidate.is_absolute():
            candidate = self.workdir / candidate
        return candidate.resolve()

    def _resolve_schedule_file(self, schedule_file: str) -> Path:
        candidate = Path(schedule_file)
        if not candidate.is_absolute():
            candidate = self.workdir / candidate
        return candidate.resolve()

    def reload_custom_tools(self) -> None:
        self.sync_custom_tools(force=True)

    def _scan_custom_tool_files(self) -> dict[str, int]:
        snapshot: dict[str, int] = {}
        if not self.custom_tool_dir.exists() or not self.custom_tool_dir.is_dir():
            return snapshot

        file_names: list[str] = []
        self._set_audit_allow_subprocess(True)
        try:
            listed = subprocess.run(
                ["ls", "-1", str(self.custom_tool_dir)],
                cwd=str(self.workdir),
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            listed = None
        finally:
            self._set_audit_allow_subprocess(False)

        if listed is not None and listed.returncode == 0:
            file_names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        else:
            file_names = [p.name for p in self.custom_tool_dir.iterdir() if p.is_file()]

        for file_name in sorted(set(file_names)):
            if not file_name.endswith(".py") or file_name.startswith("_"):
                continue
            path = (self.custom_tool_dir / file_name).resolve()
            try:
                path.relative_to(self.custom_tool_dir)
            except ValueError:
                continue
            if not path.is_file():
                continue
            try:
                snapshot[file_name] = path.stat().st_mtime_ns
            except OSError:
                continue
        return snapshot

    def sync_custom_tools(self, force: bool = False) -> bool:
        with self.custom_tools_lock:
            previous_snapshot = dict(self.custom_file_state)
            snapshot = self._scan_custom_tool_files()
            known_files = set(self.custom_file_state.keys())
            current_files = set(snapshot.keys())
            removed_files = known_files - current_files
            changed_files = {
                file_name
                for file_name in current_files
                if force or self.custom_file_state.get(file_name) != snapshot.get(file_name)
            }

            if not force and not removed_files and not changed_files:
                self.last_filesystem_scan_at = datetime.now(timezone.utc).isoformat()
                return False

            for file_name in sorted(removed_files | changed_files):
                self._unload_custom_tool_file(file_name)
                self.custom_tool_error_by_file.pop(file_name, None)

            if self.custom_tool_dir.exists() and not self.custom_tool_dir.is_dir():
                self.custom_tool_error_by_file["__custom_tool_dir__"] = f"Not a directory: {self.custom_tool_dir}"
            else:
                self.custom_tool_error_by_file.pop("__custom_tool_dir__", None)
                for file_name in sorted(changed_files):
                    self._load_custom_tool(self.custom_tool_dir / file_name)

            self.custom_file_state = snapshot
            self.last_filesystem_scan_at = datetime.now(timezone.utc).isoformat()
            self.load_errors = [self.custom_tool_error_by_file[k] for k in sorted(self.custom_tool_error_by_file.keys())]
            if force or removed_files or changed_files:
                self.tool_schema_selection_cache = {}
            return force or previous_snapshot != snapshot or bool(removed_files) or bool(changed_files)

    def _tool_runtime_context(self) -> dict[str, Any]:
        return {
            "workdir": str(self.workdir),
            "default_timeout_seconds": self.default_timeout_seconds,
            "max_output_chars": self.max_output_chars,
        }

    def _run_custom_tool_subprocess(
        self,
        tool_path: Path,
        argv: list[str],
        timeout_seconds: int,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        timeout = max(1, min(timeout_seconds, MAX_TOOL_TIMEOUT_SECONDS))
        env = os.environ.copy()
        env["AGENT_TOOL_FILE"] = str(tool_path)
        env["AGENT_TOOL_ARGV_JSON"] = json.dumps([str(item) for item in argv], ensure_ascii=False)
        env["TOOL_WORKDIR_ROOT"] = str(self.workdir)
        env["STRICT_WORKDIR_ONLY"] = "1" if self.strict_workdir_only else "0"
        strict_no_network = self.strict_workdir_only and (not allow_network)
        env["STRICT_NO_NETWORK"] = "1" if strict_no_network else "0"

        self._set_audit_allow_subprocess(True)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", TOOL_SUBPROCESS_WRAPPER],
                cwd=str(self.workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        finally:
            self._set_audit_allow_subprocess(False)
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }

    @staticmethod
    def _parse_json_from_text(text: str, context: str) -> Any:
        body = text.strip()
        if not body:
            raise ValueError(f"{context}: 출력이 비어 있습니다.")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            lines = [line.strip() for line in body.splitlines() if line.strip()]
            for line in reversed(lines):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise ValueError(f"{context}: 유효한 JSON 출력이 아닙니다.")

    def _unload_custom_tool_file(self, file_name: str) -> None:
        tool_name = self.custom_tool_file_to_name.pop(file_name, None)
        if not tool_name:
            return
        self.custom_tool_spec_map.pop(tool_name, None)
        self.custom_tool_files.pop(tool_name, None)
        self.custom_tool_sources.pop(tool_name, None)

    def _load_custom_tool(self, path: Path) -> None:
        file_name = path.name
        try:
            probe = self._run_custom_tool_subprocess(path, ["--tool-spec-json"], timeout_seconds=15)
            if int(probe.get("exit_code", 1)) != 0:
                stderr = self._trim(str(probe.get("stderr", "")))
                stdout = self._trim(str(probe.get("stdout", "")))
                self.custom_tool_error_by_file[file_name] = (
                    f"{path.name}: --tool-spec-json 실행 실패. stderr={stderr} stdout={stdout}"
                )
                return
            tool_spec = self._parse_json_from_text(str(probe.get("stdout", "")), f"{path.name} --tool-spec-json")
            if not isinstance(tool_spec, dict):
                self.custom_tool_error_by_file[file_name] = f"{path.name}: TOOL_SPEC 출력은 JSON 객체여야 합니다."
                return

            name = tool_spec.get("name")
            if not isinstance(name, str) or not name.strip():
                self.custom_tool_error_by_file[file_name] = f"{path.name}: TOOL_SPEC.name 값이 필요합니다."
                return
            name = name.strip()
            if name in self._builtin_tool_names:
                self.custom_tool_error_by_file[file_name] = f"{path.name}: '{name}'은(는) 내장 도구 이름과 충돌합니다."
                return
            if name in self.custom_tool_spec_map:
                self.custom_tool_error_by_file[file_name] = f"{path.name}: 커스텀 도구 이름 '{name}'이 중복됩니다."
                return

            description = str(tool_spec.get("description", "")).strip() or f"{path.name}에서 로드한 커스텀 도구"
            version = str(tool_spec.get("version", "")).strip() or "0.1.0"
            network_access = bool(tool_spec.get("network_access", False))
            input_schema = tool_spec.get("input_schema")
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}}

            normalized_spec = {
                "name": name,
                "description": description,
                "version": version,
                "network_access": network_access,
                "input_schema": input_schema,
            }
            self.custom_tool_spec_map[name] = normalized_spec
            try:
                rel_path = str(path.relative_to(self.workdir))
            except ValueError:
                rel_path = str(path)
            self.custom_tool_files[name] = rel_path
            self.custom_tool_sources[name] = path
            self.custom_tool_file_to_name[file_name] = name
            self.custom_tool_error_by_file.pop(file_name, None)
        except Exception as exc:
            self.custom_tool_error_by_file[file_name] = f"{path.name}: {exc}"

    def _load_jobs(self) -> None:
        with self.jobs_lock:
            if not self.schedule_file.exists():
                self.jobs = []
                return
            try:
                raw = self.schedule_file.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    self.jobs = [job for job in parsed if isinstance(job, dict)]
                else:
                    self.jobs = []
            except Exception:
                self.jobs = []

    def _save_jobs(self) -> None:
        self.schedule_file.parent.mkdir(parents=True, exist_ok=True)
        with self.jobs_lock:
            data = json.dumps(self.jobs, ensure_ascii=False, indent=2)
        self.schedule_file.write_text(data, encoding="utf-8")

    @staticmethod
    def _parse_hhmm(hhmm: str) -> tuple[int, int]:
        text = hhmm.strip()
        if not re.fullmatch(r"\d{2}:\d{2}", text):
            raise ValueError("시간(time)은 HH:MM 형식이어야 합니다.")
        hour = int(text[:2])
        minute = int(text[3:])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("시간(time)은 00:00~23:59 범위여야 합니다.")
        return hour, minute

    def _compute_next_run_utc_iso(self, hhmm: str, now_utc: datetime | None = None) -> str:
        hour, minute = self._parse_hhmm(hhmm)
        now_utc = now_utc or datetime.now(timezone.utc)
        now_local = now_utc.astimezone()
        next_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_local <= now_local:
            next_local = next_local + timedelta(days=1)
        return next_local.astimezone(timezone.utc).isoformat()

    def _is_schedulable_tool(self, tool_name: str) -> bool:
        self.sync_custom_tools()
        if tool_name in {
            "list_custom_tools",
            "reload_custom_tools",
            "tool_registry_status",
            "create_or_update_custom_tool_file",
            "delete_custom_tool_file",
            "schedule_daily_tool",
            "list_scheduled_jobs",
            "delete_scheduled_job",
            "run_due_scheduled_jobs",
        }:
            return False
        return tool_name in {spec.get("name") for spec in self.tool_specs}

    def describe_tools(self) -> list[dict[str, Any]]:
        self.sync_custom_tools()
        with self.custom_tools_lock:
            custom_names = set(self.custom_tool_spec_map.keys())
            custom_files = dict(self.custom_tool_files)
            custom_specs = dict(self.custom_tool_spec_map)
        descriptions: list[dict[str, Any]] = []
        for spec in self.tool_specs:
            required = spec.get("input_schema", {}).get("required", [])
            if not isinstance(required, list):
                required = []
            name = str(spec.get("name", ""))
            source = "custom" if name in custom_names else "builtin"
            file_path = custom_files.get(name)
            network_access = False
            if source == "custom":
                row = custom_specs.get(name)
                if isinstance(row, dict):
                    network_access = bool(row.get("network_access", False))
            descriptions.append(
                {
                    "name": name,
                    "source": source,
                    "description": spec.get("description", ""),
                    "required": required,
                    "file": file_path,
                    "network_access": network_access,
                }
            )
        return descriptions

    @property
    def tool_specs(self) -> list[dict[str, Any]]:
        self.sync_custom_tools()
        with self.custom_tools_lock:
            custom_specs = list(self.custom_tool_spec_map.values())
        base_specs = [
            {
                "name": "list_files",
                "description": "List files and directories in a relative path.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Relative path. Default is ."}},
                },
            },
            {
                "name": "read_file",
                "description": "Read a text file by path with optional line range.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "read_text_file",
                "description": "Alias of read_file. Read a text file by path with optional line range.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write text content to a file path. Creates parent directories if needed.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "append": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "save_text_file",
                "description": "Save text content to a file path under tools/ only.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "append": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "run_shell",
                "description": "프로젝트 작업 디렉토리에서 셸 명령을 실행합니다. 커스텀 도구가 있으면 run_shell로 우회 실행하지 말고 해당 도구를 직접 호출하세요.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "run_python",
                "description": "Run Python code and return stdout/stderr (blocked when strict_workdir_only is enabled).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
                    },
                    "required": ["code"],
                },
            },
            {
                "name": "list_custom_tools",
                "description": "List discovered custom tool files and loaded custom tools from the tools directory.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "reload_custom_tools",
                "description": "Reload custom tools from the tools directory so newly added tools become callable.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "tool_registry_status",
                "description": "Show filesystem scan status for custom tools including loaded tools and file metadata.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "create_or_update_custom_tool_file",
                "description": "Create or update a python tool file in the tools directory, then reload tools.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_name": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file_name", "content"],
                },
            },
            {
                "name": "delete_custom_tool_file",
                "description": "Delete a python tool file from the tools directory and unload removed tools.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_name": {"type": "string"},
                        "purge_related_schedules": {"type": "boolean"},
                    },
                    "required": ["file_name"],
                },
            },
            {
                "name": "schedule_daily_tool",
                "description": "Schedule a tool to run daily at local HH:MM time.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "time": {"type": "string", "description": "HH:MM in local time"},
                        "tool_input": {"type": "object"},
                        "description": {"type": "string"},
                    },
                    "required": ["tool_name", "time"],
                },
            },
            {
                "name": "list_scheduled_jobs",
                "description": "List all scheduled jobs.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "delete_scheduled_job",
                "description": "Delete one scheduled job by id.",
                "input_schema": {
                    "type": "object",
                    "properties": {"job_id": {"type": "string"}},
                    "required": ["job_id"],
                },
            },
            {
                "name": "run_due_scheduled_jobs",
                "description": "Run currently due scheduled jobs immediately and return execution results.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]
        return base_specs + custom_specs

    def select_tool_specs_for_prompt(self, prompt: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        all_specs = self.tool_specs
        all_by_name: dict[str, dict[str, Any]] = {}
        for spec in all_specs:
            name = str(spec.get("name", "")).strip()
            if name:
                all_by_name[name] = spec

        prompt_text = prompt.strip()
        prompt_lower = prompt_text.lower()
        schedule_keywords = ("schedule", "스케줄", "일정", "daily", "cron", "매일")
        create_keywords = ("create", "add", "new tool", "make tool", "생성", "추가", "만들", "도구 만들")
        delete_keywords = ("delete tool", "remove tool", "도구 삭제", "툴 삭제")
        reload_keywords = ("reload", "sync", "새로고침", "동기화")
        tool_admin_keywords = ("tool list", "list tools", "도구 목록", "툴 목록", "tool registry", "레지스트리", "/tools")
        file_write_keywords = (
            "write",
            "save",
            "edit",
            "modify",
            "update file",
            "파일 저장",
            "파일 수정",
            "코드 수정",
            "작성",
            "저장",
            "수정",
        )
        shell_keywords = ("run shell", "shell", "bash", "terminal", "터미널", "셸", "명령어", "ls ", "pwd", "cd ")
        python_keywords = ("run python", "python code", "파이썬 코드", "python 실행")
        arxiv_source_keywords = ("arxiv", "아카이브")
        arxiv_topic_keywords = ("논문", "paper", "papers")
        arxiv_action_keywords = (
            "요약",
            "찾",
            "검색",
            "가져",
            "정리",
            "보여",
            "불러",
            "다운로드",
            "알려",
            "list",
            "fetch",
            "search",
            "summar",
            "download",
        )
        github_keywords = ("github", "깃허브", "git hub", "pull request", "pr", "풀리퀘", "풀리퀘스트")
        calendar_keywords = (
            "calendar",
            "캘린더",
            "일정",
            "schedule",
            "회의",
            "agenda",
        )
        stock_keywords = ("주식", "stock", "ticker", "목표가", "target price", "soxx", "nasdaq", "가격 추적")
        semantic_snapshot_keywords = (
            "semantic snapshot",
            "semantic",
            "웹 스냅샷",
            "페이지 스냅샷",
            "접근성 트리",
            "accessibility tree",
            "웹 구조",
            "페이지 구조",
            "구조화",
        )
        messenger_keywords = ("telegram", "텔레그램", "메신저", "메시지 보내", "send message", "알림 전송")
        onchain_keywords = (
            "onchain",
            "on-chain",
            "온체인",
            "지갑",
            "wallet",
            "eth 주소",
            "btc 주소",
            "ethereum",
            "bitcoin",
            "블록체인",
            "잔액 조회",
            "트랜잭션 조회",
        )

        needs_schedule = any(k in prompt_lower for k in schedule_keywords)
        needs_create = any(k in prompt_lower for k in create_keywords)
        needs_delete = any(k in prompt_lower for k in delete_keywords)
        needs_reload = any(k in prompt_lower for k in reload_keywords)
        needs_tool_admin = any(k in prompt_lower for k in tool_admin_keywords)
        needs_file_write = any(k in prompt_lower for k in file_write_keywords)
        needs_shell = any(k in prompt_lower for k in shell_keywords)
        needs_python = any(k in prompt_lower for k in python_keywords)
        has_arxiv_source = any(k in prompt_lower for k in arxiv_source_keywords)
        has_arxiv_topic = any(k in prompt_lower for k in arxiv_topic_keywords)
        has_arxiv_action = any(k in prompt_lower for k in arxiv_action_keywords)
        needs_arxiv = has_arxiv_action and (has_arxiv_source or has_arxiv_topic)
        needs_github = any(k in prompt_lower for k in github_keywords)
        needs_calendar = any(k in prompt_lower for k in calendar_keywords)
        needs_stock = any(k in prompt_lower for k in stock_keywords)
        needs_semantic_snapshot = any(k in prompt_lower for k in semantic_snapshot_keywords)
        needs_messenger = any(k in prompt_lower for k in messenger_keywords)
        needs_onchain = any(k in prompt_lower for k in onchain_keywords)

        with self.custom_tools_lock:
            custom_names = sorted(self.custom_tool_spec_map.keys())
            snapshot_signature = hashlib.sha256(
                json.dumps(sorted(self.custom_file_state.items()), ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:16]

        matched_custom_names = [name for name in custom_names if name.lower() in prompt_lower]
        if needs_arxiv and "arxiv_daily_digest" in custom_names and "arxiv_daily_digest" not in matched_custom_names:
            matched_custom_names.append("arxiv_daily_digest")
        if needs_github and "github_pr_digest" in custom_names and "github_pr_digest" not in matched_custom_names:
            matched_custom_names.append("github_pr_digest")
        if needs_calendar and "google_calendar_agenda" in custom_names and "google_calendar_agenda" not in matched_custom_names:
            matched_custom_names.append("google_calendar_agenda")
        if needs_stock and "stock_price_watch" in custom_names and "stock_price_watch" not in matched_custom_names:
            matched_custom_names.append("stock_price_watch")
        if (
            needs_semantic_snapshot
            and "semantic_web_snapshot" in custom_names
            and "semantic_web_snapshot" not in matched_custom_names
        ):
            matched_custom_names.append("semantic_web_snapshot")
        if needs_messenger and "telegram_send_message" in custom_names and "telegram_send_message" not in matched_custom_names:
            matched_custom_names.append("telegram_send_message")
        if needs_onchain and "onchain_wallet_snapshot" in custom_names and "onchain_wallet_snapshot" not in matched_custom_names:
            matched_custom_names.append("onchain_wallet_snapshot")
        cache_key = json.dumps(
            {
                "snapshot": snapshot_signature,
                "schedule": needs_schedule,
                "create": needs_create,
                "delete": needs_delete,
                "reload": needs_reload,
                "tool_admin": needs_tool_admin,
                "file_write": needs_file_write,
                "shell": needs_shell,
                "python": needs_python,
                "arxiv": needs_arxiv,
                "github": needs_github,
                "calendar": needs_calendar,
                "stock": needs_stock,
                "semantic_snapshot": needs_semantic_snapshot,
                "messenger": needs_messenger,
                "onchain": needs_onchain,
                "matched_custom": matched_custom_names,
                "strict_workdir_only": self.strict_workdir_only,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        with self.custom_tools_lock:
            cached_selected = self.tool_schema_selection_cache.get(cache_key)

        cache_hit = cached_selected is not None
        if cache_hit:
            selected_names = set(cached_selected)
            with self.custom_tools_lock:
                self.tool_schema_cache_hits += 1
        else:
            selected_names = {
                "list_files",
                "read_file",
                "read_text_file",
            }
            if needs_tool_admin:
                selected_names.update({"list_custom_tools", "tool_registry_status"})
            if needs_file_write or needs_create:
                selected_names.update({"write_file", "save_text_file"})
            if needs_shell:
                selected_names.add("run_shell")
            if not self.strict_workdir_only and needs_python:
                selected_names.add("run_python")

            if needs_create:
                selected_names.update(
                    {
                        "create_or_update_custom_tool_file",
                        "delete_custom_tool_file",
                        "reload_custom_tools",
                        "list_custom_tools",
                        "tool_registry_status",
                    }
                )
            if needs_delete:
                selected_names.update({"delete_custom_tool_file", "list_custom_tools", "tool_registry_status"})
            if needs_reload:
                selected_names.update({"reload_custom_tools", "list_custom_tools", "tool_registry_status"})
            if needs_schedule:
                selected_names.update(
                    {
                        "schedule_daily_tool",
                        "list_scheduled_jobs",
                        "delete_scheduled_job",
                        "run_due_scheduled_jobs",
                    }
                )
            if ".py" in prompt_lower or "tools/" in prompt_lower:
                selected_names.update({"list_files", "read_file", "read_text_file"})
                if needs_file_write or needs_create or needs_delete:
                    selected_names.update(
                        {
                            "write_file",
                            "save_text_file",
                            "create_or_update_custom_tool_file",
                            "delete_custom_tool_file",
                        }
                    )

            selected_names.update(matched_custom_names)
            with self.custom_tools_lock:
                self.tool_schema_selection_cache[cache_key] = sorted(selected_names)
                self.tool_schema_cache_misses += 1

        selected_specs = [spec for spec in all_specs if str(spec.get("name", "")) in selected_names]
        if not selected_specs:
            selected_specs = all_specs

        full_schema_chars = len(json.dumps(all_specs, ensure_ascii=False))
        selected_schema_chars = len(json.dumps(selected_specs, ensure_ascii=False))
        reduction_pct = 0.0
        if full_schema_chars > 0:
            reduction_pct = (1.0 - (selected_schema_chars / full_schema_chars)) * 100.0
        reduction_pct = round(max(0.0, reduction_pct), 2)

        with self.custom_tools_lock:
            hit = self.tool_schema_cache_hits
            miss = self.tool_schema_cache_misses
            hit_rate = round((hit / (hit + miss)) * 100.0, 2) if (hit + miss) > 0 else 0.0

        report = {
            "cache_hit": cache_hit,
            "cache_key": cache_key,
            "total_tool_count": len(all_specs),
            "selected_tool_count": len(selected_specs),
            "full_schema_chars": full_schema_chars,
            "selected_schema_chars": selected_schema_chars,
            "estimated_reduction_pct": reduction_pct,
            "cache_hit_rate_pct": hit_rate,
            "matched_custom_tools": matched_custom_names,
            "selected_tools": [str(spec.get("name", "")) for spec in selected_specs],
        }
        with self.custom_tools_lock:
            self.last_tool_schema_report = report
        return selected_specs, report

    def run_tool(self, name: str, input_data: dict[str, Any]) -> tuple[str, bool]:
        try:
            self.sync_custom_tools()
            if name == "list_files":
                result = self._tool_list_files(str(input_data.get("path", ".")))
            elif name in {"read_file", "read_text_file"}:
                result = self._tool_read_file(
                    path=str(input_data.get("path", "")),
                    start_line=int(input_data.get("start_line", 1)),
                    end_line=int(input_data.get("end_line", 200)),
                )
            elif name == "write_file":
                result = self._tool_write_file(
                    path=str(input_data.get("path", "")),
                    content=str(input_data.get("content", "")),
                    append=bool(input_data.get("append", False)),
                )
            elif name == "save_text_file":
                result = self._tool_save_text_file(
                    path=str(input_data.get("path", "")),
                    content=str(input_data.get("content", "")),
                    append=bool(input_data.get("append", False)),
                )
            elif name == "run_shell":
                result = self._tool_run_shell(
                    command=str(input_data.get("command", "")),
                    timeout_seconds=int(input_data.get("timeout_seconds", self.default_timeout_seconds)),
                )
            elif name == "run_python":
                result = self._tool_run_python(
                    code=str(input_data.get("code", "")),
                    timeout_seconds=int(input_data.get("timeout_seconds", self.default_timeout_seconds)),
                )
            elif name == "list_custom_tools":
                result = self._tool_list_custom_tools()
            elif name == "reload_custom_tools":
                result = self._tool_reload_custom_tools()
            elif name == "tool_registry_status":
                result = self._tool_registry_status()
            elif name == "create_or_update_custom_tool_file":
                result = self._tool_create_or_update_custom_tool_file(
                    file_name=str(input_data.get("file_name", "")),
                    content=str(input_data.get("content", "")),
                )
            elif name == "delete_custom_tool_file":
                result = self._tool_delete_custom_tool_file(
                    file_name=str(input_data.get("file_name", "")),
                    purge_related_schedules=bool(input_data.get("purge_related_schedules", False)),
                )
            elif name == "schedule_daily_tool":
                result = self._tool_schedule_daily_tool(
                    tool_name=str(input_data.get("tool_name", "")),
                    hhmm=str(input_data.get("time", "")),
                    tool_input=input_data.get("tool_input", {}),
                    description=str(input_data.get("description", "")),
                )
            elif name == "list_scheduled_jobs":
                result = self._tool_list_scheduled_jobs()
            elif name == "delete_scheduled_job":
                result = self._tool_delete_scheduled_job(str(input_data.get("job_id", "")))
            elif name == "run_due_scheduled_jobs":
                result = self._tool_run_due_scheduled_jobs()
            else:
                with self.custom_tools_lock:
                    has_custom = name in self.custom_tool_spec_map
                if not has_custom:
                    self.sync_custom_tools(force=True)
                    with self.custom_tools_lock:
                        has_custom = name in self.custom_tool_spec_map
                if has_custom:
                    result = self._tool_run_custom(name=name, input_data=input_data)
                else:
                    return json.dumps({"error": f"알 수 없는 도구입니다: {name}"}, ensure_ascii=False), True
            return json.dumps(result, ensure_ascii=False), False
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False), True

    def _resolve_path(self, path: str) -> Path:
        target = (self.workdir / path).resolve()
        try:
            target.relative_to(self.workdir)
        except ValueError as exc:
            raise ValueError("경로가 작업 디렉토리 범위를 벗어났습니다.") from exc
        return target

    def _trim(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        return text[: self.max_output_chars - 3] + "..."

    def _validate_shell_args_workdir_only(self, args: list[str]) -> None:
        if not self.strict_workdir_only:
            return
        if not args:
            raise ValueError("명령어(command)는 필수입니다.")

        interpreter_block = {
            "python",
            "python3",
            "bash",
            "sh",
            "zsh",
            "node",
            "perl",
            "ruby",
            "php",
            "pwsh",
            "powershell",
        }
        network_block = {
            "curl",
            "wget",
            "ftp",
            "sftp",
            "ssh",
            "scp",
            "telnet",
            "nc",
            "ncat",
            "ping",
            "traceroute",
        }
        if args[0].startswith("/"):
            raise ValueError("strict_workdir_only 모드에서는 절대 실행 경로를 사용할 수 없습니다.")
        exec_name = Path(args[0]).name.lower()
        if exec_name in interpreter_block:
            raise ValueError("strict_workdir_only 모드에서는 인터프리터 실행이 차단됩니다.")
        if exec_name in network_block:
            raise ValueError("strict_workdir_only 모드에서는 네트워크 명령 실행이 차단됩니다.")

        for token in args[1:]:
            t = token.strip()
            if not t or t.startswith("-"):
                continue
            if t.startswith("~") or t.startswith("$"):
                raise ValueError("strict_workdir_only 모드에서는 홈/환경변수 경로 확장을 사용할 수 없습니다.")
            if t.startswith("/"):
                raise ValueError("strict_workdir_only 모드에서는 절대 경로를 사용할 수 없습니다.")
            if ".." in Path(t).parts:
                raise ValueError("strict_workdir_only 모드에서는 상위 디렉토리 이동(..)이 차단됩니다.")
            if "/" in t or t.startswith("."):
                self._resolve_path(t)

    def _tool_list_files(self, path: str) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists():
            return {"path": path, "exists": False, "entries": []}
        if not target.is_dir():
            return {"path": path, "exists": True, "is_dir": False}

        entries = []
        for entry in sorted(target.iterdir(), key=lambda p: p.name):
            entries.append({"name": entry.name, "type": "dir" if entry.is_dir() else "file"})
        return {"path": path, "exists": True, "is_dir": True, "entries": entries[:500]}

    def _tool_read_file(self, path: str, start_line: int, end_line: int) -> dict[str, Any]:
        if not path:
            raise ValueError("경로(path)는 필수입니다.")
        if start_line < 1:
            start_line = 1
        if end_line < start_line:
            end_line = start_line

        target = self._resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
        if not target.is_file():
            raise ValueError(f"파일이 아닙니다: {path}")

        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[start_line - 1 : end_line]
        numbered = [f"{idx}: {line}" for idx, line in enumerate(selected, start=start_line)]
        content = "\n".join(numbered)
        return {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": len(lines),
            "content": self._trim(content),
        }

    def _tool_write_file(self, path: str, content: str, append: bool) -> dict[str, Any]:
        if not path:
            raise ValueError("경로(path)는 필수입니다.")
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as fp:
            fp.write(content)
        return {"path": path, "written_chars": len(content), "append": append}

    def _tool_save_text_file(self, path: str, content: str, append: bool) -> dict[str, Any]:
        if not path:
            raise ValueError("경로(path)는 필수입니다.")
        target = self._resolve_path(path)
        try:
            target.relative_to(self.custom_tool_dir)
        except ValueError as exc:
            raise ValueError("save_text_file 경로는 tools/ 디렉토리 내부여야 합니다.") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as fp:
            fp.write(content)
        return {"path": path, "written_chars": len(content), "append": append}

    def _tool_run_shell(self, command: str, timeout_seconds: int) -> dict[str, Any]:
        if not command.strip():
            raise ValueError("명령어(command)는 필수입니다.")

        blocked_tokens = ["rm -rf", "sudo ", "shutdown", "reboot", "mkfs", ":(){", "dd if=", "chroot", "mount "]
        lowered = command.lower()
        if any(token in lowered for token in blocked_tokens):
            raise ValueError("보안 정책으로 차단된 명령어입니다.")

        if self.strict_workdir_only and any(ch in command for ch in [";", "|", "&", ">", "<", "`", "$(", "\\n"]):
            raise ValueError("strict_workdir_only 모드에서는 셸 메타문자를 사용할 수 없습니다.")

        try:
            args = shlex.split(command, posix=True)
        except ValueError as exc:
            raise ValueError(f"셸 명령어 문법이 올바르지 않습니다: {exc}") from exc
        if not args:
            raise ValueError("명령어(command)는 필수입니다.")
        self._validate_shell_args_workdir_only(args)

        timeout = max(1, min(timeout_seconds, MAX_TOOL_TIMEOUT_SECONDS))
        self._set_audit_allow_subprocess(True)
        try:
            result = subprocess.run(
                args,
                cwd=str(self.workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        finally:
            self._set_audit_allow_subprocess(False)
        return {
            "exit_code": result.returncode,
            "stdout": self._trim(result.stdout or ""),
            "stderr": self._trim(result.stderr or ""),
        }

    def _tool_run_python(self, code: str, timeout_seconds: int) -> dict[str, Any]:
        if not code.strip():
            raise ValueError("코드(code)는 필수입니다.")
        if self.strict_workdir_only:
            raise ValueError("strict_workdir_only 모드에서는 run_python을 사용할 수 없습니다.")
        timeout = max(1, min(timeout_seconds, MAX_TOOL_TIMEOUT_SECONDS))
        self._set_audit_allow_subprocess(True)
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(self.workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        finally:
            self._set_audit_allow_subprocess(False)
        return {
            "exit_code": result.returncode,
            "stdout": self._trim(result.stdout or ""),
            "stderr": self._trim(result.stderr or ""),
        }

    def _tool_run_custom(self, name: str, input_data: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(2):
            self.sync_custom_tools()
            with self.custom_tools_lock:
                source_path = self.custom_tool_sources.get(name)
            if source_path is None:
                raise ValueError(f"커스텀 도구를 찾을 수 없습니다: {name}")
            try:
                context = self._tool_runtime_context()
                with self.custom_tools_lock:
                    spec = self.custom_tool_spec_map.get(name, {})
                allow_network = bool(spec.get("network_access", False)) if isinstance(spec, dict) else False
                result = self._run_custom_tool_subprocess(
                    source_path,
                    [
                        "--tool-input-json",
                        json.dumps(input_data, ensure_ascii=False),
                        "--tool-context-json",
                        json.dumps(context, ensure_ascii=False),
                    ],
                    timeout_seconds=self.default_timeout_seconds,
                    allow_network=allow_network,
                )
                exit_code = int(result.get("exit_code", 1))
                stdout = str(result.get("stdout", ""))
                stderr = str(result.get("stderr", ""))
                if exit_code != 0:
                    raise RuntimeError(
                        f"커스텀 도구 '{name}' 실행 실패 (exit_code={exit_code}). stderr={self._trim(stderr)}"
                    )
                parsed = self._parse_json_from_text(stdout, f"{name} output")
                serialized = json.dumps(parsed, ensure_ascii=False, default=str)
                return {
                    "tool": name,
                    "result": self._trim(serialized),
                    "exit_code": exit_code,
                }
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise ValueError(f"커스텀 도구 실행에 실패했습니다: {name}")

    def _resolve_custom_tool_reference_path(self, file_ref: str) -> Path:
        ref = file_ref.strip()
        if not ref:
            raise ValueError("tool_ref.file 값이 필요합니다.")
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = (self.workdir / candidate).resolve()
        else:
            candidate = candidate.resolve()
        try:
            candidate.relative_to(self.custom_tool_dir)
        except ValueError as exc:
            raise ValueError("tool_ref.file은 커스텀 도구 디렉토리 내부를 가리켜야 합니다.") from exc
        return candidate

    def _resolve_custom_tool_file_path(self, file_name: str) -> Path:
        name = file_name.strip()
        if not name:
            raise ValueError("file_name 값이 필요합니다.")
        if not name.endswith(".py"):
            raise ValueError("file_name은 .py로 끝나야 합니다.")
        target = (self.custom_tool_dir / name).resolve()
        try:
            target.relative_to(self.custom_tool_dir)
        except ValueError as exc:
            raise ValueError("file_name 경로가 커스텀 도구 디렉토리 범위를 벗어났습니다.") from exc
        return target

    @staticmethod
    def _validate_custom_tool_file_content(content: str) -> None:
        required_markers = [
            "TOOL_SPEC",
            "def run(",
            "__main__",
            "--tool-spec-json",
            "--tool-input-json",
            "--tool-context-json",
            "version",
        ]
        missing = [marker for marker in required_markers if marker not in content]
        if missing:
            raise ValueError(
                "커스텀 도구 파일에 필수 계약 마커가 누락되었습니다: "
                + ", ".join(missing)
            )

    def _delete_jobs_for_tools(self, tool_names: set[str]) -> int:
        if not tool_names:
            return 0
        with self.jobs_lock:
            before = len(self.jobs)
            filtered_jobs: list[dict[str, Any]] = []
            for job in self.jobs:
                matched_tool_name = str(job.get("tool_name", ""))
                tool_ref = job.get("tool_ref")
                if isinstance(tool_ref, dict):
                    ref_name = str(tool_ref.get("tool_name", "")).strip()
                    if ref_name:
                        matched_tool_name = ref_name
                if matched_tool_name in tool_names:
                    continue
                filtered_jobs.append(job)
            self.jobs = filtered_jobs
            removed = before - len(self.jobs)
        if removed:
            self._save_jobs()
        return removed

    def _tool_list_custom_tools(self) -> dict[str, Any]:
        self.sync_custom_tools()
        with self.custom_tools_lock:
            files = sorted(self.custom_file_state.keys())
            loaded_tools = sorted(list(self.custom_tool_spec_map.keys()))
            load_errors = list(self.load_errors)
        return {
            "custom_tool_dir": str(self.custom_tool_dir),
            "files": files,
            "loaded_tools": loaded_tools,
            "load_errors": load_errors,
        }

    def _tool_reload_custom_tools(self) -> dict[str, Any]:
        self.sync_custom_tools(force=True)
        return self._tool_list_custom_tools()

    def _tool_registry_status(self) -> dict[str, Any]:
        changed = self.sync_custom_tools()
        with self.custom_tools_lock:
            tools = []
            for name, rel_path in sorted(self.custom_tool_files.items()):
                source = self.custom_tool_sources.get(name)
                spec = self.custom_tool_spec_map.get(name, {})
                mtime_ns = None
                if source is not None and source.exists():
                    try:
                        mtime_ns = source.stat().st_mtime_ns
                    except OSError:
                        mtime_ns = None
                tools.append(
                    {
                        "name": name,
                        "file": rel_path,
                        "mtime_ns": mtime_ns,
                        "network_access": bool(spec.get("network_access", False)) if isinstance(spec, dict) else False,
                    }
                )
            return {
                "custom_tool_dir": str(self.custom_tool_dir),
                "mode": "filesystem_external_process",
                "strict_workdir_only": self.strict_workdir_only,
                "last_filesystem_scan_at": self.last_filesystem_scan_at,
                "filesystem_changed": changed,
                "files": sorted(self.custom_file_state.keys()),
                "loaded_tools": tools,
                "load_errors": list(self.load_errors),
                "tool_schema_cache": {
                    "entries": len(self.tool_schema_selection_cache),
                    "hits": self.tool_schema_cache_hits,
                    "misses": self.tool_schema_cache_misses,
                    "last_report": self.last_tool_schema_report,
                },
            }

    def _tool_create_or_update_custom_tool_file(self, file_name: str, content: str) -> dict[str, Any]:
        target = self._resolve_custom_tool_file_path(file_name)
        self._validate_custom_tool_file_content(content)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.sync_custom_tools(force=True)
        with self.custom_tools_lock:
            loaded_tools = sorted(self.custom_tool_spec_map.keys())
            load_errors = list(self.load_errors)
        return {
            "file": str(target),
            "loaded_tools": loaded_tools,
            "load_errors": load_errors,
        }

    def _tool_delete_custom_tool_file(self, file_name: str, purge_related_schedules: bool) -> dict[str, Any]:
        target = self._resolve_custom_tool_file_path(file_name)
        self.sync_custom_tools()

        with self.custom_tools_lock:
            tool_names_in_file = {
                tool_name
                for tool_name, source in self.custom_tool_sources.items()
                if source.resolve() == target
            }

        deleted = False
        if target.exists():
            if not target.is_file():
                raise ValueError("대상 경로가 파일이 아닙니다.")
            target.unlink()
            deleted = True

        self.sync_custom_tools(force=True)
        removed_jobs = 0
        if purge_related_schedules and tool_names_in_file:
            removed_jobs = self._delete_jobs_for_tools(tool_names_in_file)
        with self.custom_tools_lock:
            loaded_tools = sorted(self.custom_tool_spec_map.keys())
            load_errors = list(self.load_errors)
        return {
            "file": str(target),
            "deleted": deleted,
            "removed_tools": sorted(tool_names_in_file),
            "purged_related_schedules": removed_jobs,
            "loaded_tools": loaded_tools,
            "load_errors": load_errors,
        }

    def _tool_schedule_daily_tool(
        self,
        tool_name: str,
        hhmm: str,
        tool_input: Any,
        description: str,
    ) -> dict[str, Any]:
        name = tool_name.strip()
        if not name:
            raise ValueError("tool_name 값이 필요합니다.")
        if not isinstance(tool_input, dict):
            raise ValueError("tool_input은 객체(JSON object)여야 합니다.")

        self.sync_custom_tools()
        if not self._is_schedulable_tool(name):
            raise ValueError(f"도구를 스케줄링할 수 없거나 찾을 수 없습니다: {name}")

        tool_ref: dict[str, Any]
        with self.custom_tools_lock:
            custom_file = self.custom_tool_files.get(name)
        if custom_file:
            tool_ref = {
                "kind": "custom_file",
                "file": custom_file,
                "tool_name": name,
                "entrypoint": "run",
            }
        else:
            tool_ref = {
                "kind": "builtin",
                "tool_name": name,
            }

        now_utc = datetime.now(timezone.utc)
        next_run_at = self._compute_next_run_utc_iso(hhmm, now_utc=now_utc)
        job = {
            "id": uuid4().hex[:12],
            "schedule_type": "daily",
            "time": hhmm.strip(),
            "tool_name": name,
            "tool_ref": tool_ref,
            "tool_input": tool_input,
            "description": description.strip(),
            "enabled": True,
            "created_at": now_utc.isoformat(),
            "next_run_at": next_run_at,
            "last_run_at": None,
            "last_status": None,
            "last_output_preview": None,
        }
        with self.jobs_lock:
            self.jobs.append(job)
        self._save_jobs()
        return {
            "scheduled": True,
            "job": job,
        }

    def _tool_list_scheduled_jobs(self) -> dict[str, Any]:
        with self.jobs_lock:
            jobs = json.loads(json.dumps(self.jobs, ensure_ascii=False))
        return {
            "schedule_file": str(self.schedule_file),
            "jobs": jobs,
        }

    def _tool_delete_scheduled_job(self, job_id: str) -> dict[str, Any]:
        target_id = job_id.strip()
        if not target_id:
            raise ValueError("job_id 값이 필요합니다.")

        removed = False
        with self.jobs_lock:
            before = len(self.jobs)
            self.jobs = [job for job in self.jobs if str(job.get("id", "")) != target_id]
            removed = len(self.jobs) != before
        if removed:
            self._save_jobs()
        return {"deleted": removed, "job_id": target_id}

    @staticmethod
    def _parse_utc_ts(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def get_custom_tools_snapshot(self) -> list[tuple[str, int]]:
        snapshot = self._scan_custom_tool_files()
        return sorted(snapshot.items())

    def _run_tool_by_reference(self, tool_ref: Any, tool_input: dict[str, Any]) -> tuple[str, bool, str]:
        if not isinstance(tool_ref, dict):
            return json.dumps({"error": "유효하지 않은 tool_ref 형식입니다."}, ensure_ascii=False), True, ""

        kind = str(tool_ref.get("kind", "")).strip()
        if kind == "builtin":
            tool_name = str(tool_ref.get("tool_name", "")).strip()
            result_text, is_error = self.run_tool(tool_name, tool_input)
            return result_text, is_error, tool_name

        if kind == "custom_file":
            file_ref = str(tool_ref.get("file", "")).strip()
            expected_name = str(tool_ref.get("tool_name", "")).strip() or None
            try:
                target = self._resolve_custom_tool_reference_path(file_ref)
                self.sync_custom_tools(force=True)
                chosen_name = ""
                with self.custom_tools_lock:
                    path_matches = [
                        name
                        for name, source in self.custom_tool_sources.items()
                        if source.resolve() == target
                    ]
                    if expected_name and expected_name in path_matches:
                        chosen_name = expected_name
                    elif path_matches:
                        chosen_name = path_matches[0]
                    elif expected_name and expected_name in self.custom_tool_spec_map:
                        chosen_name = expected_name
                if not chosen_name:
                    return (
                        json.dumps(
                            {
                                "error": f"파일 참조와 일치하는 로드된 도구가 없습니다: {file_ref}",
                                "expected_name": expected_name,
                            },
                            ensure_ascii=False,
                        ),
                        True,
                        expected_name or file_ref,
                    )
                result_obj = self._tool_run_custom(chosen_name, tool_input)
                return json.dumps(result_obj, ensure_ascii=False), False, chosen_name
            except Exception as exc:
                return json.dumps({"error": str(exc)}, ensure_ascii=False), True, expected_name or file_ref

        return json.dumps({"error": f"지원하지 않는 tool_ref 종류입니다: {kind}"}, ensure_ascii=False), True, ""

    def run_due_scheduled_jobs(self) -> list[dict[str, Any]]:
        now_utc = datetime.now(timezone.utc)
        due_job_ids: list[str] = []

        with self.jobs_lock:
            for job in self.jobs:
                if not job.get("enabled", True):
                    continue
                if job.get("schedule_type") != "daily":
                    continue
                run_at = self._parse_utc_ts(job.get("next_run_at"))
                if run_at is None:
                    continue
                if run_at <= now_utc:
                    due_job_ids.append(str(job.get("id", "")))

        if not due_job_ids:
            return []

        results: list[dict[str, Any]] = []
        for job_id in due_job_ids:
            with self.jobs_lock:
                job = next((x for x in self.jobs if str(x.get("id", "")) == job_id), None)
            if not job:
                continue

            tool_input = job.get("tool_input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}
            tool_ref = job.get("tool_ref")
            if isinstance(tool_ref, dict):
                result_text, is_error, executed_tool_name = self._run_tool_by_reference(tool_ref, tool_input)
            else:
                # Legacy job format fallback.
                legacy_tool_name = str(job.get("tool_name", ""))
                result_text, is_error = self.run_tool(legacy_tool_name, tool_input)
                executed_tool_name = legacy_tool_name
            status = "error" if is_error else "ok"
            now_run = datetime.now(timezone.utc)
            try:
                next_run = self._compute_next_run_utc_iso(str(job.get("time", "00:00")), now_utc=now_run)
            except Exception:
                next_run = (now_run + timedelta(days=1)).isoformat()

            with self.jobs_lock:
                for item in self.jobs:
                    if str(item.get("id", "")) == job_id:
                        item["last_run_at"] = now_run.isoformat()
                        item["last_status"] = status
                        item["last_output_preview"] = self._trim(result_text)
                        item["next_run_at"] = next_run
                        break

            results.append(
                {
                    "job_id": job_id,
                    "tool_name": executed_tool_name,
                    "status": status,
                    "result": self._trim(result_text),
                }
            )

        self._save_jobs()
        return results

    def _tool_run_due_scheduled_jobs(self) -> dict[str, Any]:
        executions = self.run_due_scheduled_jobs()
        return {"executions": executions}

    def shutdown(self) -> None:
        with self.custom_tools_lock:
            for file_name in sorted(list(self.custom_tool_file_to_name.keys())):
                self._unload_custom_tool_file(file_name)
            self.custom_tool_error_by_file.clear()
            self.load_errors = []


def main() -> None:
    from builtin_tools import BuiltinTools
    from config import BoramClawConfig
    from guardian import format_guardian_report, run_guardian_preflight
    from gateway import ClaudeChat as GatewayClaudeChat
    from health_server import start_health_server
    from logger import ChatLogger as ModularChatLogger
    from memory_store import LongTermMemoryStore
    from messenger_bridge import TelegramBridge
    from metrics_dashboard import build_dashboard_snapshot, render_dashboard_text
    from multi_agent import MultiAgentCoordinator, format_agent_selection
    from reflexion_store import ReflexionStore, append_self_heal_feedback
    from scheduler import JobScheduler
    from rules_engine import RulesEngine
    from self_expansion import SelfExpansionLoop
    from tool_executor import PolicyToolExecutor
    from web_ui_server import start_web_ui_server

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging")
    parser.add_argument("--dry-run", action="store_true", help="Do not execute tools; only simulate")
    parser.add_argument("--force-tool-use", action="store_true", help="Force tool_choice=any when tools are available")
    parser.add_argument("--health-port", type=int, default=0, help="Override health server port")
    parser.add_argument("--install-daemon", action="store_true", help="Install daemon service (LaunchAgent/systemd)")
    parser.add_argument("--uninstall-daemon", action="store_true", help="Uninstall daemon service (LaunchAgent/systemd)")
    parser.add_argument("--daemon-dry-run", action="store_true", help="Dry-run for daemon install/uninstall")
    parser.add_argument("--dashboard", action="store_true", help="Print runtime metrics dashboard and exit")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup wizard and exit")
    parser.add_argument("--setup-non-interactive", action="store_true", help="Run non-interactive setup wizard and exit")
    parser.add_argument("--web-ui", action="store_true", help="Start web ui server")
    parser.add_argument("--web-ui-port", type=int, default=0, help="Override web ui port")
    parser.add_argument("--telegram", action="store_true", help="Start telegram bridge")
    args = parser.parse_args()

    try:
        if handle_daemon_service_command(
            install=args.install_daemon,
            uninstall=args.uninstall_daemon,
            dry_run=args.daemon_dry_run,
        ):
            return
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    if args.setup or args.setup_non_interactive:
        from setup_wizard import run_setup_wizard

        result = run_setup_wizard(
            env_path=".env",
            non_interactive=bool(args.setup_non_interactive),
            updates={},
        )
        print(json.dumps(result, ensure_ascii=False))
        return

    if args.dashboard:
        workdir = (os.getenv("TOOL_WORKDIR") or ".").strip()
        snapshot = build_dashboard_snapshot(workdir=workdir)
        print(render_dashboard_text(snapshot))
        return

    config = BoramClawConfig.from_env()
    if not config.anthropic_api_key and sys.stdin.isatty():
        config.anthropic_api_key = getpass.getpass("Anthropic API key: ").strip()
    if args.debug:
        config.debug = True
    if args.dry_run:
        config.dry_run = True
    if args.force_tool_use:
        config.force_tool_use = True
    if args.health_port > 0:
        config.health_port = args.health_port

    guardian_report = run_guardian_preflight(
        config=config,
        check_dependencies=config.check_dependencies_on_start,
        auto_fix=_bool_env_local("GUARDIAN_AUTO_FIX", False),
        auto_install_deps=_bool_env_local("GUARDIAN_AUTO_INSTALL_DEPS", False),
    )
    if int(guardian_report.get("issue_count", 0)) > 0:
        print(format_guardian_report(guardian_report), file=sys.stderr)
    if int(guardian_report.get("critical_count", 0)) > 0:
        raise SystemExit(1)

    if config.debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.debug("debug mode enabled")

    workdir = config.tool_workdir
    show_tool_schema_opt = config.debug or _bool_env_local("SHOW_TOOL_SCHEMA_OPT", False)
    token_metrics_path = Path(os.getenv("TOKEN_USAGE_FILE") or "logs/token_usage.jsonl")
    if not token_metrics_path.is_absolute():
        token_metrics_path = Path(workdir).resolve() / token_metrics_path
    token_input_price = _float_env_local("TOKEN_PRICE_INPUT_PER_1M", 0.0)
    token_output_price = _float_env_local("TOKEN_PRICE_OUTPUT_PER_1M", 0.0)

    base_system_prompt = config.claude_system_prompt or DEFAULT_SYSTEM_PROMPT
    system_prompt = (
        f"{base_system_prompt}\n"
        "추가 규칙: 사용자와의 응답은 항상 한국어로 작성하세요. "
        "커스텀 도구가 존재하면 run_shell로 우회 실행하지 말고 해당 도구를 직접 호출하세요. "
        "일반 질의에서 도구 파일 생성/수정(save_text_file, create_or_update_custom_tool_file)을 먼저 시도하지 마세요."
    )
    encrypt_key = config.chat_log_encryption_key
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = config.chat_log_file
    if config.session_log_split:
        base_dir = Path(config.log_base_dir)
        if not base_dir.is_absolute():
            base_dir = Path(workdir).resolve() / base_dir
        log_file = str((base_dir / f"session_{session_id}" / "chat.jsonl"))
    logger = ModularChatLogger(log_file=log_file, session_id=session_id)
    logger.log(
        "session_start",
        payload="chat started",
        model=config.claude_model,
        max_tokens=config.claude_max_tokens,
        workdir=workdir,
        modular_architecture=True,
    )

    base_tools = ToolExecutor(
        workdir=workdir,
        default_timeout_seconds=config.tool_timeout_seconds,
        custom_tool_dir=config.custom_tool_dir,
        schedule_file=config.schedule_file,
        strict_workdir_only=config.strict_workdir_only,
    )

    permissions = config.permissions_map()
    if not permissions:
        permissions = BuiltinTools(workdir=workdir, strict_mode=config.strict_workdir_only).default_permissions()

    def approval_callback(tool_name: str, input_data: dict[str, Any]) -> bool:
        if not sys.stdin.isatty():
            return False
        print(f"\n⚠️ 도구 '{tool_name}' 실행 승인이 필요합니다.")
        print(json.dumps(input_data, ensure_ascii=False, indent=2))
        response = input("실행할까요? (y/n): ").strip().lower()
        return response in {"y", "yes", "네", "예", "ㅇ"}

    tools = PolicyToolExecutor(
        base_executor=base_tools,
        permissions=permissions,
        approval_callback=approval_callback,
        dry_run=config.dry_run,
    )

    self_expansion_model = (os.getenv("SELF_EXPANSION_MODEL") or config.claude_model).strip()
    self_expander = SelfExpansionLoop(
        api_key=config.anthropic_api_key,
        model=self_expansion_model,
        workdir=workdir,
        custom_tool_dir=config.custom_tool_dir,
        tool_executor=tools,
    )

    chat = GatewayClaudeChat(
        api_key=config.anthropic_api_key,
        model=config.claude_model,
        max_tokens=config.claude_max_tokens,
        system_prompt=system_prompt,
        force_tool_use=config.force_tool_use,
    )
    memory_store = LongTermMemoryStore(
        workdir=workdir,
        file_path=(os.getenv("LONG_TERM_MEMORY_FILE") or "logs/long_term_memory.jsonl"),
        max_records=int(os.getenv("LONG_TERM_MEMORY_MAX_RECORDS") or "20000"),
    )
    reflexion_store = ReflexionStore(
        workdir=workdir,
        file_path=(os.getenv("REFLEXION_FILE") or "logs/reflexion_cases.jsonl"),
        max_records=int(os.getenv("REFLEXION_MAX_RECORDS") or "10000"),
    )
    multi_agent = MultiAgentCoordinator()
    multi_agent_auto_route = _bool_env_local("MULTI_AGENT_AUTO_ROUTE", False)

    last_tool_snapshot = tools.get_custom_tools_snapshot()
    session_memory: list[str] = []
    self_expand_pending = False
    tool_only_mode = bool(config.force_tool_use)

    def remember_exchange(role: str, text: str) -> None:
        session_memory.append(f"{role}: {summarize_for_memory(text)}")
        if len(session_memory) > 12:
            del session_memory[:-12]
        try:
            memory_store.add(session_id=session_id, turn=logger.turn, role=role, text=text)
        except Exception:
            pass

    def emit_answer(answer: str) -> None:
        if not answer:
            return
        display_answer = format_user_output(answer)
        remember_exchange("A", display_answer)
        logger.log("assistant_output", payload=safe_log_payload(display_answer, encrypt_key))
        print(display_answer)

    def has_tool(tool_name: str) -> bool:
        return any(item.get("name") == tool_name for item in tools.describe_tools())

    def append_agent_feedback(payload: dict[str, Any]) -> None:
        try:
            feedback_path = Path(workdir).resolve() / "logs" / "agent_feedback.jsonl"
            feedback_path.parent.mkdir(parents=True, exist_ok=True)
            row = {"ts": datetime.now(timezone.utc).isoformat(), "session_id": session_id, **payload}
            with feedback_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            append_self_heal_feedback(workdir=workdir, payload={"session_id": session_id, **payload})
        except Exception:
            return

    def add_reflexion_case(
        *,
        kind: str,
        input_text: str,
        outcome: str,
        fix: str = "",
        severity: str = "warn",
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            reflexion_store.add_case(
                kind=kind,
                input_text=input_text,
                outcome=outcome,
                fix=fix,
                severity=severity,
                source=source,
                metadata=metadata or {},
            )
        except Exception:
            return

    def run_self_expansion_cycle(trigger: str, force: bool = False) -> dict[str, Any]:
        result = self_expander.run_cycle(trigger=trigger, force=force)
        logger.log(
            "self_expansion_cycle",
            payload=safe_log_payload(json.dumps(result, ensure_ascii=False), encrypt_key),
        )
        if bool(result.get("changed")):
            try:
                tools.sync_custom_tools(force=True)
            except Exception:
                pass
            reset_chat_if_tools_changed()
        return result

    def reset_chat_if_tools_changed() -> None:
        nonlocal last_tool_snapshot
        current_snapshot = tools.get_custom_tools_snapshot()
        if current_snapshot == last_tool_snapshot:
            return
        summary = "\n".join(session_memory[-8:])
        chat.reset_session(summary=summary)
        logger.log(
            "chat_session_reset",
            payload=safe_log_payload("custom tool files changed; recreated chat session", encrypt_key),
            reason="custom_tools_changed",
        )
        last_tool_snapshot = current_snapshot

    def on_tool_event(name: str, input_data: dict[str, Any], result_text: str, is_error: bool) -> None:
        nonlocal self_expand_pending
        if name == "react_feedback":
            logger.log("react_feedback", payload=safe_log_payload(result_text, encrypt_key))
            append_agent_feedback(
                {
                    "event": "react_feedback",
                    "detail": input_data,
                    "message": result_text,
                    "is_error": is_error,
                }
            )
            self_expand_pending = True
            return
        logger.log_tool_call(name, input_data)
        event = "tool_error" if is_error else "tool_result"
        logger.log(event, payload=safe_log_payload(result_text, encrypt_key))
        if is_error:
            add_reflexion_case(
                kind=f"tool_error:{name}",
                input_text=json.dumps(input_data, ensure_ascii=False),
                outcome=result_text,
                fix="도구 입력값/권한/타임아웃을 점검하고 필요하면 /feedback으로 개선 지시를 남긴다.",
                source="tool_event",
                metadata={"tool_name": name},
            )

    def run_chat_turn(prompt_text: str, delegated: bool) -> tuple[str, dict[str, Any]]:
        if delegated:
            result = multi_agent.handle_turn(
                chat=chat,
                user_input=prompt_text,
                select_tool_specs=tools.select_tool_specs_for_prompt,
                tool_runner=tools.run_tool,
                on_tool_event=on_tool_event,
                force_tool_use=tool_only_mode,
            )
            selection_info = {"agent": str(result.get("agent", "")), "reason": str(result.get("agent_reason", ""))}
            logger.log("agent_delegation", payload=safe_log_payload(format_agent_selection(selection_info), encrypt_key))
            schema_report = result.get("schema_report")
            if not isinstance(schema_report, dict):
                schema_report = {}
            logger.log(
                "tool_schema_selection",
                payload=safe_log_payload(json.dumps(schema_report, ensure_ascii=False), encrypt_key),
            )
            return str(result.get("answer", "")), schema_report

        selected_tool_specs, schema_report = tools.select_tool_specs_for_prompt(prompt_text)
        logger.log(
            "tool_schema_selection",
            payload=safe_log_payload(json.dumps(schema_report, ensure_ascii=False), encrypt_key),
        )
        previous_force_tool_use = bool(getattr(chat, "force_tool_use", False))
        setattr(chat, "force_tool_use", previous_force_tool_use or tool_only_mode)
        try:
            answer = chat.ask(
                prompt_text,
                tools=selected_tool_specs,
                tool_runner=tools.run_tool,
                on_tool_event=on_tool_event,
            )
        finally:
            setattr(chat, "force_tool_use", previous_force_tool_use)
        return answer, schema_report

    interaction_lock = threading.Lock()

    def process_external_request(user_text: str, source: str = "external") -> str:
        nonlocal self_expand_pending
        prompt = user_text.strip()
        if not prompt:
            return "빈 요청입니다."
        with interaction_lock:
            reset_chat_if_tools_changed()
            logger.next_turn()
            logger.log("user_prompt", payload=safe_log_payload(prompt, encrypt_key), source=source)
            remember_exchange("U", prompt)
            try:
                if is_tool_list_request(prompt):
                    answer = format_tool_list(tools)
                    display_answer = format_user_output(answer)
                    remember_exchange("A", display_answer)
                    logger.log("assistant_output", payload=safe_log_payload(display_answer, encrypt_key), source=source)
                    return display_answer

                parsed_tool_cmd = parse_tool_command(prompt)
                if parsed_tool_cmd is not None:
                    tool_name, tool_input = parsed_tool_cmd
                    result_text, is_error = tools.run_tool(tool_name, tool_input)
                    on_tool_event(tool_name, tool_input, result_text, is_error)
                    answer = result_text
                else:
                    quick_arxiv_input = parse_arxiv_quick_request(prompt)
                    if quick_arxiv_input is not None and has_tool("arxiv_daily_digest"):
                        result_text, is_error = tools.run_tool("arxiv_daily_digest", quick_arxiv_input)
                        on_tool_event("arxiv_daily_digest", quick_arxiv_input, result_text, is_error)
                        answer = result_text
                    else:
                        delegate_input = parse_delegate_command(prompt)
                        delegated_turn = delegate_input is not None or multi_agent_auto_route
                        model_prompt = delegate_input if delegate_input is not None else prompt
                        answer, _ = run_chat_turn(prompt_text=model_prompt, delegated=delegated_turn)

                if (
                    "도구 호출 루프가 제한 횟수를 초과" in answer
                    or "도구 호출이 같은 형태로 반복되어 중단" in answer
                ):
                    append_agent_feedback(
                        {
                            "event": "react_feedback",
                            "detail": {"kind": "external_loop_message", "source": source},
                            "message": answer,
                            "is_error": True,
                        }
                    )
                    self_expand_pending = True
                if self_expand_pending:
                    run_self_expansion_cycle(trigger=f"{source}_react_feedback", force=False)
                    self_expand_pending = False

                display_answer = format_user_output(answer)
                remember_exchange("A", display_answer)
                logger.log("assistant_output", payload=safe_log_payload(display_answer, encrypt_key), source=source)
                return display_answer
            except Exception as exc:
                message = str(exc)
                logger.log("error_output", payload=safe_log_payload(message, encrypt_key), source=source)
                add_reflexion_case(
                    kind="external_request_error",
                    input_text=prompt,
                    outcome=message,
                    fix="외부 인터페이스 입력 형식과 도구 권한 정책을 점검",
                    severity="error",
                    source=source,
                )
                return message

    scheduler: JobScheduler | None = None
    rules_engine: RulesEngine | None = None

    # Rules Engine 초기화 (config/rules.yaml 있을 때만)
    rules_file = Path("config/rules.yaml")
    if rules_file.exists():
        try:
            rules_engine = RulesEngine(str(rules_file))
            if rules_engine.load_rules():
                logger.log("rules_engine_loaded", payload=f"{len(rules_engine.rules)}개 규칙 로드 완료")
            else:
                rules_engine = None
        except Exception as exc:
            logger.log("rules_engine_error", payload=f"규칙 로드 실패: {exc}")
            rules_engine = None

    def on_scheduler_heartbeat(hb: dict) -> None:
        """Scheduler heartbeat 콜백 - 로그 + Rules Engine 평가"""
        # 1. 기존 로그
        logger.log(
            "heartbeat",
            payload=safe_log_payload(json.dumps(hb, ensure_ascii=False), encrypt_key),
        )

        # 2. Rules Engine 평가 (활성화된 경우)
        if rules_engine and rules_engine.config.get("enabled", True):
            try:
                executed_actions = rules_engine.evaluate_rules(
                    repo_path=config.tool_workdir,
                    tool_executor=tools,
                )
                if executed_actions:
                    logger.log(
                        "rules_engine_actions",
                        payload=safe_log_payload(
                            json.dumps({"actions": executed_actions}, ensure_ascii=False),
                            encrypt_key
                        ),
                    )
            except Exception as exc:
                logger.log("rules_engine_error", payload=f"규칙 평가 실패: {exc}")

    health_server = None
    if config.health_server_enabled:
        try:
            health_server = start_health_server(port=config.health_port, agent_mode=config.agent_mode)
            logger.log("health_server_start", payload=f"listening on 127.0.0.1:{config.health_port}")
        except Exception as exc:
            logger.log("health_server_error", payload=str(exc))
    if config.scheduler_enabled:
        scheduler = JobScheduler(
            poll_seconds=config.scheduler_poll_seconds,
            tool_executor=tools,
            on_job_run=lambda item: logger.log(
                "scheduled_job_run",
                payload=safe_log_payload(json.dumps(item, ensure_ascii=False), encrypt_key),
            ),
            on_heartbeat=on_scheduler_heartbeat,
        )
        scheduler.start()

    web_ui_server = None
    web_ui_enabled = args.web_ui or _bool_env_local("WEB_UI_ENABLED", False)
    web_ui_port = int(os.getenv("WEB_UI_PORT") or "8091")
    if args.web_ui_port > 0:
        web_ui_port = args.web_ui_port
    if web_ui_enabled:
        try:
            web_ui_server = start_web_ui_server(
                ask_callback=lambda message: process_external_request(message, source="web_ui"),
                port=web_ui_port,
            )
            logger.log("web_ui_start", payload=f"listening on 127.0.0.1:{web_ui_server.port}")
        except Exception as exc:
            logger.log("web_ui_error", payload=str(exc))

    telegram_bridge = None
    telegram_enabled = args.telegram or _bool_env_local("TELEGRAM_ENABLED", False)
    if telegram_enabled:
        bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        if not bot_token:
            logger.log("telegram_bridge_error", payload="TELEGRAM_ENABLED=1 이지만 TELEGRAM_BOT_TOKEN이 비어 있습니다.")
        else:
            chat_id_raw = (os.getenv("TELEGRAM_ALLOWED_CHAT_ID") or "").strip()
            allowed_chat_id = None
            if chat_id_raw:
                try:
                    allowed_chat_id = int(chat_id_raw)
                except ValueError:
                    allowed_chat_id = None
            poll_interval = _float_env_local("TELEGRAM_POLL_SECONDS", 1.0)
            try:
                telegram_bridge = TelegramBridge(
                    bot_token=bot_token,
                    ask_callback=lambda message: process_external_request(message, source="telegram"),
                    allowed_chat_id=allowed_chat_id,
                    poll_interval_seconds=poll_interval,
                    on_log=lambda row: logger.log("telegram_bridge", payload=row),
                )
                telegram_bridge.start()
                logger.log("telegram_bridge_start", payload="telegram bridge started")
            except Exception as exc:
                logger.log("telegram_bridge_error", payload=str(exc))

    if config.agent_mode == "daemon":
        if not config.scheduler_enabled:
            message = "데몬 모드에서는 SCHEDULER_ENABLED=1 설정이 필요합니다."
            logger.log("error_output", payload=safe_log_payload(message, encrypt_key))
            print(message, file=sys.stderr)
            if scheduler is not None:
                scheduler.stop()
            raise SystemExit(1)
        logger.log("daemon_mode", payload="scheduler daemon started", poll_seconds=config.scheduler_poll_seconds)
        try:
            while True:
                threading.Event().wait(60)
        except KeyboardInterrupt:
            logger.log("session_end", payload="daemon interrupted")
        if scheduler is not None:
            scheduler.stop()
        if health_server is not None:
            health_server.stop()
        if web_ui_server is not None:
            web_ui_server.stop()
        if telegram_bridge is not None:
            telegram_bridge.stop()
        tools.shutdown()
        return

    while True:
        try:
            user_input = input("BoramClaw가 실행 중입니다. 보람이 이르시되 ").strip()
        except (EOFError, KeyboardInterrupt):
            logger.log("session_end", payload="input stream closed")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            logger.log("session_end", payload="user exited")
            break

        reset_chat_if_tools_changed()
        logger.next_turn()
        logger.log("user_prompt", payload=safe_log_payload(user_input, encrypt_key))
        remember_exchange("U", user_input)

        try:
            if is_tool_list_request(user_input):
                answer = format_tool_list(tools)
                emit_answer(answer)
                continue

            if user_input.strip().lower() in {
                "/reload-tools",
                "/sync-tools",
                "reload tools",
                "sync tools",
                "도구 새로고침",
                "툴 새로고침",
                "도구 동기화",
                "툴 동기화",
            }:
                tools.sync_custom_tools(force=True)
                answer = format_tool_list(tools)
                emit_answer(answer)
                continue

            if is_schedule_list_request(user_input):
                answer = json.dumps(tools._tool_list_scheduled_jobs(), ensure_ascii=False, indent=2)
                emit_answer(answer)
                continue

            schedule_arxiv = parse_schedule_arxiv_command(user_input)
            if schedule_arxiv is not None:
                if not has_tool("arxiv_daily_digest"):
                    emit_answer("arxiv_daily_digest 도구가 없어 스케줄을 등록할 수 없습니다.")
                    continue
                schedule_payload = {
                    "tool_name": "arxiv_daily_digest",
                    "time": str(schedule_arxiv.get("time", "08:00")),
                    "tool_input": {
                        "keywords": list(schedule_arxiv.get("keywords", ["llm"])),
                        "max_papers": 5,
                        "days_back": 1,
                        "output": "file",
                        "output_file": "logs/daily_arxiv.md",
                    },
                    "description": "Daily arXiv digest",
                }
                result_text, is_error = tools.run_tool("schedule_daily_tool", schedule_payload)
                on_tool_event("schedule_daily_tool", schedule_payload, result_text, is_error)
                emit_answer(result_text)
                continue

            today_cmd = parse_today_command(user_input)
            if today_cmd is not None:
                if not has_tool("workday_recap"):
                    emit_answer("workday_recap 도구가 없습니다.")
                    continue
                recap_input = {"mode": "daily"}
                if "focus_keyword" in today_cmd:
                    recap_input["focus_keyword"] = today_cmd["focus_keyword"]
                result_text, is_error = tools.run_tool("workday_recap", recap_input)
                on_tool_event("workday_recap", recap_input, result_text, is_error)
                if is_error:
                    emit_answer(f"리포트 생성 실패: {result_text}")
                else:
                    try:
                        result_data = json.loads(result_text) if isinstance(result_text, str) else result_text
                        formatted = format_workday_recap(result_data)
                        emit_answer(formatted)
                    except Exception as e:
                        emit_answer(f"리포트 포맷팅 실패: {e}\n\n원본:\n{result_text}")
                continue

            week_cmd = parse_week_command(user_input)
            if week_cmd is not None:
                if not has_tool("workday_recap"):
                    emit_answer("workday_recap 도구가 없습니다.")
                    continue
                recap_input = {"mode": "weekly"}
                if "focus_keyword" in week_cmd:
                    recap_input["focus_keyword"] = week_cmd["focus_keyword"]
                result_text, is_error = tools.run_tool("workday_recap", recap_input)
                on_tool_event("workday_recap", recap_input, result_text, is_error)
                if is_error:
                    emit_answer(f"리포트 생성 실패: {result_text}")
                else:
                    try:
                        result_data = json.loads(result_text) if isinstance(result_text, str) else result_text
                        formatted = format_workday_recap(result_data)
                        emit_answer(formatted)
                    except Exception as e:
                        emit_answer(f"리포트 포맷팅 실패: {e}\n\n원본:\n{result_text}")
                continue

            context_cmd = parse_context_command(user_input)
            if context_cmd is not None:
                if not has_tool("get_current_context"):
                    emit_answer("get_current_context 도구가 없습니다.")
                    continue
                context_input = {}
                if "lookback_minutes" in context_cmd:
                    context_input["lookback_minutes"] = context_cmd["lookback_minutes"]
                result_text, is_error = tools.run_tool("get_current_context", context_input)
                on_tool_event("get_current_context", context_input, result_text, is_error)
                emit_answer(result_text)
                continue

            memory_cmd = parse_memory_command(user_input)
            if memory_cmd is not None:
                action = str(memory_cmd.get("action", ""))
                if action == "status":
                    answer = json.dumps(memory_store.status(), ensure_ascii=False, indent=2)
                elif action == "latest":
                    count = int(memory_cmd.get("count", 5) or 5)
                    answer = json.dumps({"latest": memory_store.latest(count=count)}, ensure_ascii=False, indent=2)
                elif action == "query":
                    query_text = str(memory_cmd.get("text", "")).strip()
                    answer = format_memory_query_result(query_text, memory_store.query(query_text, top_k=5))
                else:
                    answer = "지원하지 않는 memory 명령입니다."
                emit_answer(answer)
                continue

            if user_input.strip().lower() in {"/dashboard", "/metrics", "대시보드", "메트릭"}:
                snapshot = build_dashboard_snapshot(workdir=workdir)
                answer = render_dashboard_text(snapshot)
                emit_answer(answer)
                continue

            reflexion_cmd = parse_reflexion_command(user_input)
            if reflexion_cmd is not None:
                action = str(reflexion_cmd.get("action", ""))
                if action == "status":
                    answer = json.dumps(reflexion_store.status(), ensure_ascii=False, indent=2)
                elif action == "latest":
                    count = int(reflexion_cmd.get("count", 10) or 10)
                    answer = format_reflexion_records(reflexion_store.latest(count=count))
                elif action == "query":
                    query_text = str(reflexion_cmd.get("text", "")).strip()
                    answer = format_reflexion_records(reflexion_store.query(query_text, top_k=8))
                else:
                    answer = "지원하지 않는 reflexion 명령입니다."
                emit_answer(answer)
                continue

            feedback_text = parse_feedback_command(user_input)
            if feedback_text is not None:
                reflexion_store.add_feedback(text=feedback_text, source="user")
                append_self_heal_feedback(
                    workdir=workdir,
                    payload={
                        "event": "user_feedback",
                        "session_id": session_id,
                        "text": feedback_text,
                    },
                )
                answer = "피드백을 기록했습니다. 다음 자가개선 사이클에서 반영됩니다."
                emit_answer(answer)
                continue

            if user_input.strip().lower() in {"/permissions", "permissions", "권한 목록", "권한 정책"}:
                answer = format_permissions_map(permissions)
                emit_answer(answer)
                continue

            permission_cmd = parse_set_permission_command(user_input)
            if permission_cmd is not None:
                target_tool, target_mode = permission_cmd
                permissions[target_tool] = target_mode
                tools.set_permissions(permissions)
                answer = f"권한 업데이트 완료: {target_tool} -> {target_mode}"
                emit_answer(answer)
                continue

            if user_input.strip().lower() in {"/run-due-jobs", "run due jobs", "지금 스케줄 실행"}:
                answer = json.dumps(tools._tool_run_due_scheduled_jobs(), ensure_ascii=False, indent=2)
                emit_answer(answer)
                continue

            if user_input.strip().lower() in {"/self-expand", "/selfexpand", "self expand", "자가개선", "자가개선 실행"}:
                result = run_self_expansion_cycle(trigger="manual", force=True)
                answer = json.dumps(result, ensure_ascii=False, indent=2)
                emit_answer(answer)
                continue

            delegate_input = parse_delegate_command(user_input)
            delegated_turn = delegate_input is not None or multi_agent_auto_route
            model_prompt = delegate_input if delegate_input is not None else user_input

            parsed_tool_cmd = parse_tool_command(user_input)
            if parsed_tool_cmd is not None:
                tool_name, tool_input = parsed_tool_cmd
                result_text, is_error = tools.run_tool(tool_name, tool_input)
                on_tool_event(tool_name, tool_input, result_text, is_error)
                answer = result_text
                emit_answer(answer)
                continue

            tool_only_cmd = parse_tool_only_mode_command(user_input)
            if tool_only_cmd is not None:
                tool_only_mode = bool(tool_only_cmd)
                state = "활성화" if tool_only_mode else "비활성화"
                answer = f"도구 전용 모드를 {state}했습니다."
                emit_answer(answer)
                continue

            quick_arxiv_input = parse_arxiv_quick_request(user_input)
            if delegate_input is None and quick_arxiv_input is not None and has_tool("arxiv_daily_digest"):
                result_text, is_error = tools.run_tool("arxiv_daily_digest", quick_arxiv_input)
                on_tool_event("arxiv_daily_digest", quick_arxiv_input, result_text, is_error)
                answer = result_text
                emit_answer(answer)
                continue

            answer, schema_report = run_chat_turn(prompt_text=model_prompt, delegated=delegated_turn)
            if not schema_report:
                schema_report = {
                    "selected_tool_count": 0,
                    "total_tool_count": len(tools.describe_tools()),
                    "selected_schema_chars": 0,
                    "full_schema_chars": 0,
                    "estimated_reduction_pct": 0.0,
                    "cache_hit": False,
                    "cache_hit_rate_pct": 0.0,
                }
            usage_snapshot = {}
            consume_usage = getattr(chat, "consume_pending_usage", None)
            if callable(consume_usage):
                try:
                    usage_snapshot = consume_usage()
                except Exception:
                    usage_snapshot = {}
            if isinstance(usage_snapshot, dict):
                input_tokens = int(usage_snapshot.get("input_tokens", 0) or 0)
                output_tokens = int(usage_snapshot.get("output_tokens", 0) or 0)
                request_count = int(usage_snapshot.get("requests", 0) or 0)
                total_tokens = input_tokens + output_tokens
                if request_count > 0:
                    estimated_cost_usd = ((input_tokens * token_input_price) + (output_tokens * token_output_price)) / 1_000_000
                    usage_row = {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "session_id": session_id,
                        "turn": logger.turn,
                        "model": config.claude_model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                        "requests": request_count,
                        "estimated_cost_usd": round(max(0.0, estimated_cost_usd), 8),
                    }
                    token_metrics_path.parent.mkdir(parents=True, exist_ok=True)
                    with token_metrics_path.open("a", encoding="utf-8") as fp:
                        fp.write(json.dumps(usage_row, ensure_ascii=False) + "\n")
                    logger.log(
                        "token_usage",
                        payload=safe_log_payload(json.dumps(usage_row, ensure_ascii=False), encrypt_key),
                    )
            if (
                "도구 호출 루프가 제한 횟수를 초과" in answer
                or "도구 호출이 같은 형태로 반복되어 중단" in answer
            ):
                append_agent_feedback(
                    {
                        "event": "react_feedback",
                        "detail": {"kind": "loop_message"},
                        "message": answer,
                        "is_error": True,
                    }
                )
                self_expand_pending = True
            optimization_line = (
                "[tool-schema-opt] "
                f"selected={schema_report['selected_tool_count']}/{schema_report['total_tool_count']} "
                f"chars={schema_report['selected_schema_chars']}/{schema_report['full_schema_chars']} "
                f"saved={schema_report['estimated_reduction_pct']}% "
                f"cache_hit={schema_report['cache_hit']} "
                f"cache_hit_rate={schema_report['cache_hit_rate_pct']}%"
            )
            if show_tool_schema_opt:
                answer = f"{answer}\n{optimization_line}" if answer else optimization_line
            if self_expand_pending:
                expand_result = run_self_expansion_cycle(trigger="react_feedback", force=False)
                self_expand_pending = False
                if bool(expand_result.get("changed")):
                    changed_file = str(expand_result.get("plan_tool_file") or "")
                    if changed_file:
                        answer = f"{answer}\n[자가개선] {changed_file} 갱신됨" if answer else f"[자가개선] {changed_file} 갱신됨"
        except (RuntimeError, ValueError) as exc:
            error_message = str(exc)
            logger.log("error_output", payload=safe_log_payload(error_message, encrypt_key))
            remember_exchange("A", error_message)
            add_reflexion_case(
                kind="runtime_exception",
                input_text=user_input,
                outcome=error_message,
                fix="입력 의도 분기/도구 권한/루프 제한 조건을 점검",
                severity="error",
                source="main_loop",
            )
            print(error_message, file=sys.stderr)
            if "Tool loop exceeded maximum rounds" in error_message or "도구 호출 루프가 제한 횟수를 초과" in error_message:
                append_agent_feedback(
                    {
                        "event": "react_feedback",
                        "detail": {"kind": "max_tool_rounds_exception"},
                        "message": error_message,
                        "is_error": True,
                    }
                )
                try:
                    run_self_expansion_cycle(trigger="loop_exception", force=False)
                except Exception:
                    pass
            continue

        emit_answer(answer)

    if scheduler is not None:
        scheduler.stop()
    if health_server is not None:
        health_server.stop()
    if web_ui_server is not None:
        web_ui_server.stop()
    if telegram_bridge is not None:
        telegram_bridge.stop()
    tools.shutdown()


if __name__ == "__main__":
    main()
