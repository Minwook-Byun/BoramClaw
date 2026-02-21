#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_windows_gateway_bundle(root: Path) -> list[str]:
    scripts_root = root / "scripts" / "windows"
    created: list[str] = []

    start_script = scripts_root / "start_gateway.bat"
    _write_text(
        start_script,
        "@echo off\n"
        "setlocal\n"
        "set ROOT=%~dp0..\\..\\\n"
        "cd /d \"%ROOT%\"\n"
        "if not exist \"config\\vc_gateway.json\" (\n"
        "  echo [ERROR] config\\vc_gateway.json not found.\n"
        "  exit /b 1\n"
        ")\n"
        "if defined BORAMCLAW_PYTHON_BIN (\n"
        "  \"%BORAMCLAW_PYTHON_BIN%\" vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.14 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.14 vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.13 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.13 vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.12 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.12 vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.11 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.11 vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.10 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.10 vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3 vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "python -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  python vc_gateway_agent.py --config config\\vc_gateway.json --host 0.0.0.0 --port 8742\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "echo [ERROR] Python launcher (py) or python executable not found.\n"
        "exit /b 1\n",
    )
    created.append(str(start_script))

    install_script = scripts_root / "install_gateway_service.bat"
    _write_text(
        install_script,
        "@echo off\n"
        "setlocal\n"
        "set ROOT=%~dp0..\\..\\\n"
        "cd /d \"%ROOT%\"\n"
        "if defined BORAMCLAW_PYTHON_BIN (\n"
        "  \"%BORAMCLAW_PYTHON_BIN%\" install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.14 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.14 install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.13 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.13 install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.12 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.12 install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.11 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.11 install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.10 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.10 install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3 install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "python -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  python install_daemon.py --install --mode gateway --gateway-config config\\vc_gateway.json\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "echo [ERROR] Python launcher (py) or python executable not found.\n"
        "exit /b 1\n",
    )
    created.append(str(install_script))

    uninstall_script = scripts_root / "uninstall_gateway_service.bat"
    _write_text(
        uninstall_script,
        "@echo off\n"
        "setlocal\n"
        "set ROOT=%~dp0..\\..\\\n"
        "cd /d \"%ROOT%\"\n"
        "if defined BORAMCLAW_PYTHON_BIN (\n"
        "  \"%BORAMCLAW_PYTHON_BIN%\" install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.14 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.14 install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.13 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.13 install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.12 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.12 install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.11 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.11 install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3.10 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3.10 install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "py -3 -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  py -3 install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "python -V >nul 2>&1\n"
        "if %ERRORLEVEL% EQU 0 (\n"
        "  python install_daemon.py --uninstall --mode gateway\n"
        "  exit /b %ERRORLEVEL%\n"
        ")\n"
        "echo [ERROR] Python launcher (py) or python executable not found.\n"
        "exit /b 1\n",
    )
    created.append(str(uninstall_script))

    return created


def _ask(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    return raw


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized in {"central", "vc", "orchestrator"}:
        return "central"
    if normalized in {"gateway", "startup"}:
        return "gateway"
    raise ValueError("mode must be central or gateway")


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


def run_vc_setup_wizard(
    *,
    workdir: str = ".",
    env_path: str = ".env",
    mode: str = "central",
    non_interactive: bool = False,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    VC/AC 사용자를 위한 쉬운 설정 위저드.

    - central: VC 오케스트레이터 설정 + tenant 템플릿 생성
    - gateway: 스타트업 PC 게이트웨이 설정 생성
    """
    resolved_mode = _normalize_mode(mode)
    root = Path(workdir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    updates = updates or {}

    # 공통 디렉토리 생성
    for rel in ("config", "data", "vault", "logs"):
        (root / rel).mkdir(parents=True, exist_ok=True)

    env_file = (root / env_path).resolve()
    env_values = _read_env(env_file)
    for key, val in DEFAULTS.items():
        env_values.setdefault(key, val)
    env_values.setdefault("TOOL_WORKDIR", str(root))

    # 기본값
    defaults: dict[str, str] = {
        "startup_id": "acme",
        "display_name": "Acme AI",
        "gateway_url": "http://127.0.0.1:8742",
        "folder_alias": "desktop_common",
        "gateway_secret": "change-me",
        "gateway_folder_path": str((Path.home() / "Desktop" / "common").resolve()),
        "email_recipients": "partner@vc.com,ops@vc.com",
        "telegram_enabled": "1",
        "telegram_bot_token": env_values.get("TELEGRAM_BOT_TOKEN", ""),
        "telegram_allowed_chat_id": env_values.get("TELEGRAM_ALLOWED_CHAT_ID", ""),
        "smtp_host": env_values.get("VC_SMTP_HOST", ""),
        "smtp_port": env_values.get("VC_SMTP_PORT", "587"),
        "smtp_user": env_values.get("VC_SMTP_USER", ""),
        "smtp_password": env_values.get("VC_SMTP_PASSWORD", ""),
        "smtp_from": env_values.get("VC_SMTP_FROM", ""),
    }
    for key, value in updates.items():
        if key and value is not None:
            defaults[str(key)] = str(value)

    if not non_interactive:
        print("\n=== OpenClaw VC 쉬운 설정 ===")
        print("비개발자 기준으로 필요한 것만 질문합니다.\n")
        defaults["startup_id"] = _ask("스타트업 ID (영문/숫자)", defaults["startup_id"])
        defaults["display_name"] = _ask("표시 이름", defaults["display_name"])
        if resolved_mode == "central":
            defaults["gateway_url"] = _ask("스타트업 게이트웨이 URL", defaults["gateway_url"])
            defaults["folder_alias"] = _ask("공용 폴더 별칭", defaults["folder_alias"])
            defaults["gateway_secret"] = _ask("게이트웨이 공유 비밀키", defaults["gateway_secret"])
            defaults["email_recipients"] = _ask("리포트 수신 메일(쉼표 구분)", defaults["email_recipients"])
            defaults["telegram_enabled"] = _ask("텔레그램 사용(1/0)", defaults["telegram_enabled"])
            defaults["telegram_bot_token"] = _ask("텔레그램 봇 토큰", defaults["telegram_bot_token"])
            defaults["telegram_allowed_chat_id"] = _ask("허용 Chat ID", defaults["telegram_allowed_chat_id"])
            defaults["smtp_host"] = _ask("SMTP HOST(없으면 비워두기)", defaults["smtp_host"])
            defaults["smtp_port"] = _ask("SMTP PORT", defaults["smtp_port"])
            defaults["smtp_user"] = _ask("SMTP USER", defaults["smtp_user"])
            defaults["smtp_password"] = _ask("SMTP PASSWORD", defaults["smtp_password"])
            defaults["smtp_from"] = _ask("SMTP FROM", defaults["smtp_from"])
        else:
            defaults["gateway_folder_path"] = _ask("공유할 폴더 경로", defaults["gateway_folder_path"])
            defaults["folder_alias"] = _ask("폴더 별칭", defaults["folder_alias"])
            defaults["gateway_secret"] = _ask("게이트웨이 공유 비밀키", defaults["gateway_secret"])

    startup_id = defaults["startup_id"].strip().lower() or "acme"
    display_name = defaults["display_name"].strip() or startup_id
    folder_alias = defaults["folder_alias"].strip() or "desktop_common"
    gateway_secret = defaults["gateway_secret"].strip()

    created_paths: list[str] = []
    if resolved_mode == "central":
        recipients = [item.strip() for item in defaults["email_recipients"].split(",") if item.strip()]
        tenant_payload = {
            "tenants": [
                {
                    "startup_id": startup_id,
                    "display_name": display_name,
                    "gateway_url": defaults["gateway_url"].strip(),
                    "folder_alias": folder_alias,
                    "gateway_secret": gateway_secret,
                    "allowed_doc_types": [
                        "business_registration",
                        "ir_deck",
                        "tax_invoice",
                        "social_insurance",
                        "investment_decision",
                    ],
                    "email_recipients": recipients,
                    "active": True,
                }
            ]
        }
        tenant_path = root / "config" / "vc_tenants.json"
        _write_json(tenant_path, tenant_payload)
        created_paths.append(str(tenant_path))

        env_values["TELEGRAM_ENABLED"] = defaults["telegram_enabled"].strip() or "1"
        env_values["TELEGRAM_BOT_TOKEN"] = defaults["telegram_bot_token"].strip()
        env_values["TELEGRAM_ALLOWED_CHAT_ID"] = defaults["telegram_allowed_chat_id"].strip()
        env_values["VC_SMTP_HOST"] = defaults["smtp_host"].strip()
        env_values["VC_SMTP_PORT"] = defaults["smtp_port"].strip() or "587"
        env_values["VC_SMTP_USER"] = defaults["smtp_user"].strip()
        env_values["VC_SMTP_PASSWORD"] = defaults["smtp_password"].strip()
        env_values["VC_SMTP_FROM"] = defaults["smtp_from"].strip()
    else:
        gateway_folder = Path(defaults["gateway_folder_path"]).expanduser().resolve()
        gateway_folder.mkdir(parents=True, exist_ok=True)
        gateway_payload = {
            "startup_id": startup_id,
            "shared_secret": gateway_secret,
            "max_artifacts": 500,
            "folders": {
                folder_alias: str(gateway_folder),
            },
        }
        gateway_path = root / "config" / "vc_gateway.json"
        _write_json(gateway_path, gateway_payload)
        created_paths.append(str(gateway_path))
        created_paths.extend(_create_windows_gateway_bundle(root))

    _write_env(env_file, env_values)
    created_paths.append(str(env_file))

    next_steps: list[str] = []
    if resolved_mode == "central":
        next_steps = [
            "python3 main.py --telegram",
            f"/vc onboard {startup_id} 7d",
            f"/vc scope {startup_id}",
            f"/vc collect {startup_id} 7d",
            "/vc pending",
        ]
    else:
        if platform.system() == "Windows":
            next_steps = [
                "scripts\\windows\\start_gateway.bat",
                "scripts\\windows\\install_gateway_service.bat",
            ]
        else:
            next_steps = [
                "python3 vc_gateway_agent.py --config config/vc_gateway.json --host 0.0.0.0 --port 8742",
                "python3 install_daemon.py --install --mode gateway --gateway-config config/vc_gateway.json",
            ]

    return {
        "ok": True,
        "mode": resolved_mode,
        "workdir": str(root),
        "startup_id": startup_id,
        "display_name": display_name,
        "created_files": created_paths,
        "next_steps": next_steps,
        "validation_command": (
            f"/vc onboard {startup_id} 7d"
            if resolved_mode == "central"
            else (
                "scripts\\windows\\start_gateway.bat"
                if platform.system() == "Windows"
                else "python3 vc_gateway_agent.py --config config/vc_gateway.json --host 0.0.0.0 --port 8742"
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BoramClaw setup wizard")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--vc-mode", default="", help="VC setup mode: central or gateway")
    parser.add_argument("--workdir", default=".", help="Working directory for VC setup")
    parser.add_argument("--startup-id", default="")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--gateway-url", default="")
    parser.add_argument("--folder-alias", default="")
    parser.add_argument("--gateway-secret", default="")
    parser.add_argument("--gateway-folder-path", default="")
    parser.add_argument("--email-recipients", default="")
    args = parser.parse_args()

    updates: dict[str, str] = {}
    if args.api_key.strip():
        updates["ANTHROPIC_API_KEY"] = args.api_key.strip()
    if args.model.strip():
        updates["CLAUDE_MODEL"] = args.model.strip()

    if args.vc_mode.strip():
        vc_updates: dict[str, Any] = {}
        for key, value in {
            "startup_id": args.startup_id,
            "display_name": args.display_name,
            "gateway_url": args.gateway_url,
            "folder_alias": args.folder_alias,
            "gateway_secret": args.gateway_secret,
            "gateway_folder_path": args.gateway_folder_path,
            "email_recipients": args.email_recipients,
        }.items():
            if value.strip():
                vc_updates[key] = value.strip()
        result = run_vc_setup_wizard(
            workdir=args.workdir,
            env_path=args.env,
            mode=args.vc_mode,
            non_interactive=bool(args.non_interactive),
            updates=vc_updates,
        )
    else:
        result = run_setup_wizard(
            env_path=args.env,
            non_interactive=bool(args.non_interactive),
            updates=updates,
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
