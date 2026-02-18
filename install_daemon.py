#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
from pathlib import Path
import subprocess
import sys


def get_root() -> Path:
    return Path.cwd().resolve()


def build_macos_plist(root: Path, python_path: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.boramclaw.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{root}/watchdog_runner.py</string>
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
    <key>EnvironmentVariables</key>
    <dict>
        <key>AGENT_MODE</key>
        <string>daemon</string>
    </dict>
</dict>
</plist>
"""


def build_linux_service(root: Path, python_path: str) -> str:
    return f"""[Unit]
Description=BoramClaw Autonomous Agent
After=network.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={python_path} {root}/watchdog_runner.py
Restart=always
RestartSec=10
Environment="AGENT_MODE=daemon"
StandardOutput=append:{root}/logs/daemon_stdout.log
StandardError=append:{root}/logs/daemon_stderr.log

[Install]
WantedBy=default.target
"""


def install_macos(dry_run: bool) -> None:
    root = get_root()
    plist_path = Path.home() / "Library/LaunchAgents/com.boramclaw.agent.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_content = build_macos_plist(root, sys.executable)
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


def install_linux(dry_run: bool) -> None:
    root = get_root()
    service_dir = Path.home() / ".config/systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / "boramclaw.service"
    service_path.write_text(build_linux_service(root, sys.executable), encoding="utf-8")
    if dry_run:
        print(f"[DRY-RUN] wrote service: {service_path}")
        return
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "boramclaw.service"], check=True)
    subprocess.run(["systemctl", "--user", "start", "boramclaw.service"], check=True)
    print(f"✅ systemd service installed: {service_path}")


def uninstall_linux(dry_run: bool) -> None:
    service_path = Path.home() / ".config/systemd/user/boramclaw.service"
    if dry_run:
        print(f"[DRY-RUN] would stop/disable and delete: {service_path}")
        return
    subprocess.run(["systemctl", "--user", "stop", "boramclaw.service"], check=False)
    subprocess.run(["systemctl", "--user", "disable", "boramclaw.service"], check=False)
    service_path.unlink(missing_ok=True)
    print("✅ systemd service uninstalled")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install/uninstall BoramClaw daemon service")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.install and not args.uninstall:
        parser.print_help()
        return 1

    system = platform.system()
    if args.install:
        if system == "Darwin":
            install_macos(dry_run=args.dry_run)
            return 0
        if system == "Linux":
            install_linux(dry_run=args.dry_run)
            return 0
        print(f"❌ Unsupported platform: {system}")
        return 1

    if system == "Darwin":
        uninstall_macos(dry_run=args.dry_run)
        return 0
    if system == "Linux":
        uninstall_linux(dry_run=args.dry_run)
        return 0
    print(f"❌ Unsupported platform: {system}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

