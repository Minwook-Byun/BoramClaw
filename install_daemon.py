#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path
import re
import subprocess
import sys


def get_root() -> Path:
    return Path.cwd().resolve()


def _parse_major_minor(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)\s*", text or "")
    if match is None:
        raise ValueError(f"invalid version format: {text!r} (expected major.minor)")
    return int(match.group(1)), int(match.group(2))


def _probe_python_major_minor(python_bin: str) -> tuple[int, int]:
    try:
        result = subprocess.run(
            [
                python_bin,
                "-c",
                "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"python executable not found: {python_bin}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() or "<no output>"
        raise RuntimeError(f"failed to probe python version: {python_bin}, detail={detail}") from exc
    output = (result.stdout or "").strip()
    try:
        return _parse_major_minor(output)
    except ValueError as exc:
        raise RuntimeError(f"unexpected python version probe output: {output!r}") from exc


def resolve_python_bin(*, python_bin: str | None = None, min_python: str = "3.10") -> str:
    env_python_bin = (os.getenv("BORAMCLAW_PYTHON_BIN") or "").strip()
    candidate = (python_bin or "").strip() or env_python_bin or sys.executable
    required = _parse_major_minor((os.getenv("BORAMCLAW_MIN_PYTHON") or "").strip() or min_python)

    same_as_sys = False
    try:
        same_as_sys = Path(candidate).resolve() == Path(sys.executable).resolve()
    except Exception:
        same_as_sys = candidate == sys.executable

    if same_as_sys:
        current = (int(sys.version_info.major), int(sys.version_info.minor))
    else:
        current = _probe_python_major_minor(candidate)
    if current < required:
        raise RuntimeError(
            f"python version too low: python={candidate}, detected={current[0]}.{current[1]}, required>={required[0]}.{required[1]}"
        )
    return candidate


def build_macos_plist(
    root: Path,
    python_path: str,
    *,
    mode: str = "agent",
    gateway_config: str = "config/vc_gateway.json",
) -> str:
    if mode == "gateway":
        args = [
            f"        <string>{python_path}</string>",
            f"        <string>{root}/vc_gateway_agent.py</string>",
            "        <string>--config</string>",
            f"        <string>{gateway_config}</string>",
        ]
        env_block = ""
    else:
        args = [
            f"        <string>{python_path}</string>",
            f"        <string>{root}/watchdog_runner.py</string>",
        ]
        env_block = """    <key>EnvironmentVariables</key>
    <dict>
        <key>AGENT_MODE</key>
        <string>daemon</string>
    </dict>
"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.boramclaw.agent</string>
    <key>ProgramArguments</key>
    <array>
{chr(10).join(args)}
    </array>
    <key>WorkingDirectory</key>
    <string>{root}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{root}/logs/daemon_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{root}/logs/daemon_stderr.log</string>
{env_block}
</dict>
</plist>
"""


def build_linux_service(
    root: Path,
    python_path: str,
    *,
    mode: str = "agent",
    gateway_config: str = "config/vc_gateway.json",
) -> str:
    if mode == "gateway":
        exec_start = f"{python_path} {root}/vc_gateway_agent.py --config {gateway_config}"
        env_line = ""
    else:
        exec_start = f"{python_path} {root}/watchdog_runner.py"
        env_line = 'Environment="AGENT_MODE=daemon"'
    return f"""[Unit]
Description=BoramClaw Autonomous Agent
After=network.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={exec_start}
Restart=always
RestartSec=10
{env_line}
StandardOutput=append:{root}/logs/daemon_stdout.log
StandardError=append:{root}/logs/daemon_stderr.log

[Install]
WantedBy=default.target
"""


def _resolve_gateway_config_path(root: Path, gateway_config: str) -> Path:
    path = Path(gateway_config)
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()
    return path


def _quote_windows(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def build_windows_command(
    root: Path,
    python_path: str,
    *,
    mode: str = "agent",
    gateway_config: str = "config/vc_gateway.json",
) -> str:
    if mode == "gateway":
        cfg_path = _resolve_gateway_config_path(root, gateway_config)
        return (
            f"{_quote_windows(python_path)} "
            f"{_quote_windows(str(root / 'vc_gateway_agent.py'))} "
            f"--config {_quote_windows(str(cfg_path))}"
        )
    runner = (
        f"{_quote_windows(python_path)} "
        f"{_quote_windows(str(root / 'watchdog_runner.py'))}"
    )
    return f'cmd /c "set AGENT_MODE=daemon && {runner}"'


def _windows_task_name(mode: str) -> str:
    if mode == "gateway":
        return "BoramClawGateway"
    return "BoramClawAgent"


def _windows_schtasks_hint(returncode: int) -> str:
    if returncode == 1:
        return "권한 부족(관리자 권한) 또는 잘못된 인자일 수 있습니다."
    if returncode == 2:
        return "작업 이름 충돌, 경로 오타, 또는 schtasks 구문 오류일 수 있습니다."
    return "schtasks 출력(stdout/stderr) 내용을 확인하세요."


def _raise_windows_schtasks_error(
    *,
    action: str,
    task_name: str,
    command: list[str],
    exc: subprocess.CalledProcessError,
) -> None:
    stdout = (exc.stdout or "").strip()
    stderr = (exc.stderr or "").strip()
    detail = stderr or stdout or "<no output>"
    hint = _windows_schtasks_hint(exc.returncode)
    raise RuntimeError(
        f"Windows scheduled task {action} 실패: task={task_name}, exit={exc.returncode}, hint={hint}, detail={detail}, command={' '.join(command)}"
    ) from exc


def install_macos(
    dry_run: bool,
    *,
    mode: str = "agent",
    gateway_config: str = "config/vc_gateway.json",
    python_bin: str | None = None,
    min_python: str = "3.10",
) -> None:
    root = get_root()
    python_path = resolve_python_bin(python_bin=python_bin, min_python=min_python)
    plist_path = Path.home() / "Library/LaunchAgents/com.boramclaw.agent.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_content = build_macos_plist(root, python_path, mode=mode, gateway_config=gateway_config)
    plist_path.write_text(plist_content, encoding="utf-8")
    if dry_run:
        print(f"[DRY-RUN] wrote plist: {plist_path}")
        return
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    print(f"✅ LaunchAgent installed: {plist_path}")


def uninstall_macos(dry_run: bool) -> None:
    plist_path = Path.home() / "Library/LaunchAgents/com.boramclaw.agent.plist"
    if not plist_path.exists():
        print("⚠️ No LaunchAgent found")
        return
    if dry_run:
        print(f"[DRY-RUN] would unload and delete: {plist_path}")
        return
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    plist_path.unlink(missing_ok=True)
    print("✅ LaunchAgent uninstalled")


def install_linux(
    dry_run: bool,
    *,
    mode: str = "agent",
    gateway_config: str = "config/vc_gateway.json",
    python_bin: str | None = None,
    min_python: str = "3.10",
) -> None:
    root = get_root()
    python_path = resolve_python_bin(python_bin=python_bin, min_python=min_python)
    service_dir = Path.home() / ".config/systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / "boramclaw.service"
    service_path.write_text(
        build_linux_service(root, python_path, mode=mode, gateway_config=gateway_config),
        encoding="utf-8",
    )
    if dry_run:
        print(f"[DRY-RUN] wrote service: {service_path}")
        return
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "boramclaw.service"], check=True)
    subprocess.run(["systemctl", "--user", "start", "boramclaw.service"], check=True)
    print(f"✅ systemd service installed: {service_path}")


def install_windows(
    dry_run: bool,
    *,
    mode: str = "agent",
    gateway_config: str = "config/vc_gateway.json",
    python_bin: str | None = None,
    min_python: str = "3.10",
    task_schedule: str = "ONLOGON",
    task_delay: str = "",
    task_user: str = "",
) -> None:
    root = get_root()
    python_path = resolve_python_bin(python_bin=python_bin, min_python=min_python)
    task_name = _windows_task_name(mode)
    schedule = (task_schedule or "ONLOGON").strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]+", schedule):
        raise RuntimeError(f"invalid Windows task schedule: {task_schedule!r}")
    delay = (task_delay or "").strip()
    task_user_value = (task_user or "").strip()
    command = build_windows_command(root, python_path, mode=mode, gateway_config=gateway_config)
    create_cmd = [
        "schtasks",
        "/Create",
        "/F",
        "/SC",
        schedule,
        "/TN",
        task_name,
        "/TR",
        command,
    ]
    if delay:
        create_cmd.extend(["/DELAY", delay])
    if task_user_value:
        create_cmd.extend(["/RU", task_user_value])
    if dry_run:
        print(f"[DRY-RUN] would create scheduled task: {task_name}")
        print(f"[DRY-RUN] command: {' '.join(create_cmd)}")
        return
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", task_name],
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(create_cmd, check=True, capture_output=True, text=True)
        run_cmd = ["schtasks", "/Run", "/TN", task_name]
        run_result = subprocess.run(run_cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("`schtasks` 명령을 찾을 수 없습니다. Windows 작업 스케줄러가 필요합니다.") from exc
    except subprocess.CalledProcessError as exc:
        _raise_windows_schtasks_error(action="install", task_name=task_name, command=create_cmd, exc=exc)
    if run_result.returncode != 0:
        stdout = (run_result.stdout or "").strip()
        stderr = (run_result.stderr or "").strip()
        detail = stderr or stdout or "<no output>"
        hint = _windows_schtasks_hint(run_result.returncode)
        print(
            f"⚠️ task created but immediate run failed: task={task_name}, exit={run_result.returncode}, hint={hint}, detail={detail}"
        )
    print(f"✅ Scheduled task installed: {task_name}")


def uninstall_linux(dry_run: bool) -> None:
    service_path = Path.home() / ".config/systemd/user/boramclaw.service"
    if dry_run:
        print(f"[DRY-RUN] would stop/disable and delete: {service_path}")
        return
    subprocess.run(["systemctl", "--user", "stop", "boramclaw.service"], check=False)
    subprocess.run(["systemctl", "--user", "disable", "boramclaw.service"], check=False)
    service_path.unlink(missing_ok=True)
    print("✅ systemd service uninstalled")


def uninstall_windows(dry_run: bool, *, mode: str = "agent") -> None:
    task_name = _windows_task_name(mode)
    if dry_run:
        print(f"[DRY-RUN] would delete scheduled task: {task_name}")
        return
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", task_name],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("`schtasks` 명령을 찾을 수 없습니다. Windows 작업 스케줄러가 필요합니다.") from exc
    if result.returncode != 0:
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        detail = (stderr or stdout).lower()
        if "cannot find" in detail or "찾을 수 없습니다" in detail:
            print(f"⚠️ Scheduled task not found: {task_name}")
            return
        hint = _windows_schtasks_hint(result.returncode)
        raise RuntimeError(
            f"Windows scheduled task uninstall 실패: task={task_name}, exit={result.returncode}, hint={hint}, detail={stderr or stdout or '<no output>'}"
        )
    print(f"✅ Scheduled task uninstalled: {task_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install/uninstall BoramClaw daemon service")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mode", choices=["agent", "gateway"], default="agent")
    parser.add_argument("--gateway-config", default="config/vc_gateway.json")
    parser.add_argument("--python-bin", default="")
    parser.add_argument("--min-python", default=(os.getenv("BORAMCLAW_MIN_PYTHON") or "3.10"))
    parser.add_argument(
        "--windows-task-schedule",
        default=(os.getenv("BORAMCLAW_WINDOWS_TASK_SCHEDULE") or "ONLOGON"),
    )
    parser.add_argument("--windows-task-delay", default=(os.getenv("BORAMCLAW_WINDOWS_TASK_DELAY") or ""))
    parser.add_argument("--windows-task-user", default=(os.getenv("BORAMCLAW_WINDOWS_TASK_USER") or ""))
    args = parser.parse_args()

    if not args.install and not args.uninstall:
        parser.print_help()
        return 1

    system = platform.system()
    if args.install:
        if system == "Darwin":
            install_macos(
                dry_run=args.dry_run,
                mode=args.mode,
                gateway_config=args.gateway_config,
                python_bin=args.python_bin or None,
                min_python=args.min_python,
            )
            return 0
        if system == "Linux":
            install_linux(
                dry_run=args.dry_run,
                mode=args.mode,
                gateway_config=args.gateway_config,
                python_bin=args.python_bin or None,
                min_python=args.min_python,
            )
            return 0
        if system == "Windows":
            install_windows(
                dry_run=args.dry_run,
                mode=args.mode,
                gateway_config=args.gateway_config,
                python_bin=args.python_bin or None,
                min_python=args.min_python,
                task_schedule=args.windows_task_schedule,
                task_delay=args.windows_task_delay,
                task_user=args.windows_task_user,
            )
            return 0
        print(f"❌ Unsupported platform: {system}")
        return 1

    if system == "Darwin":
        uninstall_macos(dry_run=args.dry_run)
        return 0
    if system == "Linux":
        uninstall_linux(dry_run=args.dry_run)
        return 0
    if system == "Windows":
        uninstall_windows(dry_run=args.dry_run, mode=args.mode)
        return 0
    print(f"❌ Unsupported platform: {system}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
