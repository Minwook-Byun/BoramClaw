#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
from pathlib import Path
import shutil
import subprocess
import sys


LABEL = "com.boram.autodashboard-timeseries-sync"


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_codex_command() -> str:
    env_value = ""
    try:
        import os

        env_value = str(os.getenv("CODEX_COMMAND", "")).strip()
    except Exception:
        env_value = ""
    if env_value:
        return env_value
    return shutil.which("codex") or "codex"


def build_macos_plist(
    *,
    root: Path,
    python_path: str,
    autodashboard_root: Path,
    hour: int,
    minute: int,
    hourly: bool,
    kinds: str,
    days_back: int,
    start_at: str,
    focus: str,
    codex_command: str,
) -> str:
    sync_script = root / "tools" / "daily_wrapup_pipeline.py"
    logs_dir = root / "logs"
    autodashboard_file = autodashboard_root / "app" / "dashboard" / "timeseries" / "snapshots.jsonl"
    retrospective_posts_file = autodashboard_root / "app" / "dashboard" / "retrospectives" / "posts.jsonl"
    fallback_file = logs_dir / "autodashboard_timeseries_sync_fallback.jsonl"

    header = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{sync_script}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{root}</string>
    <key>RunAtLoad</key>
    <false/>
    <key>StartCalendarInterval</key>
"""
    if hourly:
        schedule_block = f"""    <dict>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
"""
    else:
        schedule_block = f"""    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
"""

    return header + schedule_block + f"""
    <key>StandardOutPath</key>
    <string>{logs_dir / "daily_wrapup_pipeline_stdout.log"}</string>
    <key>StandardErrorPath</key>
    <string>{logs_dir / "daily_wrapup_pipeline_stderr.log"}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{root}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>CODEX_COMMAND</key>
        <string>{codex_command}</string>
        <key>SESSION_TIMESERIES_FILE</key>
        <string>{root / "logs" / "session_timeseries.jsonl"}</string>
        <key>BORAMCLAW_WRAPUP_HISTORY_FILE</key>
        <string>{Path.home() / ".codex" / "history.jsonl"}</string>
        <key>BORAMCLAW_CODEX_SESSIONS_ROOT</key>
        <string>{Path.home() / ".codex" / "sessions"}</string>
        <key>BORAMCLAW_WRAPUP_DAILY_FOCUS</key>
        <string>{focus}</string>
        <key>BORAMCLAW_WRAPUP_CODEX_TIMEOUT_SECONDS</key>
        <string>180</string>
        <key>BORAMCLAW_RETROSPECTIVE_OUTPUT_DIR</key>
        <string>{root / "logs" / "reviews" / "daily"}</string>
        <key>BORAMCLAW_RETROSPECTIVE_REPO_ROOTS</key>
        <string>{root},{Path.home() / "Desktop" / "AutoDashboard"},{Path.home() / "InnerPlatform-ft-izzie-latest"},{Path.home() / "Hwp" / "hwpx-report-automation" / "web"}</string>
        <key>AUTO_DASHBOARD_TIMESERIES_FILE</key>
        <string>{autodashboard_file}</string>
        <key>AUTO_DASHBOARD_RETROSPECTIVE_POSTS_FILE</key>
        <string>{retrospective_posts_file}</string>
        <key>AUTO_DASHBOARD_TIMESERIES_FALLBACK_FILE</key>
        <string>{fallback_file}</string>
        <key>AUTO_DASHBOARD_TIMESERIES_KINDS</key>
        <string>{kinds}</string>
        <key>AUTO_DASHBOARD_TIMESERIES_DAYS_BACK</key>
        <string>{days_back}</string>
        <key>AUTO_DASHBOARD_TIMESERIES_NOT_BEFORE</key>
        <string>{start_at}</string>
    </dict>
</dict>
</plist>
"""


def install_macos(
    *,
    autodashboard_root: Path,
    hour: int,
    minute: int,
    hourly: bool,
    kinds: str,
    days_back: int,
    start_at: str,
    focus: str,
    codex_command: str,
    dry_run: bool,
) -> Path:
    root = repo_root()
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    plist_content = build_macos_plist(
        root=root,
        python_path=sys.executable,
        autodashboard_root=autodashboard_root,
        hour=hour,
        minute=minute,
        hourly=hourly,
        kinds=kinds,
        days_back=days_back,
        start_at=start_at,
        focus=focus,
        codex_command=codex_command,
    )
    plist_path.write_text(plist_content, encoding="utf-8")
    if dry_run:
        return plist_path

    uid = str(subprocess.check_output(["id", "-u"], text=True).strip())
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], check=False)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)], check=True)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{LABEL}"], check=False)
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"], check=False)
    return plist_path


def uninstall_macos(dry_run: bool) -> Path:
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    if dry_run or not plist_path.exists():
        return plist_path
    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], check=False)
    plist_path.unlink(missing_ok=True)
    return plist_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install BoramClaw daily wrapup + AutoDashboard sync on macOS launchd")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--autodashboard-root", default=str(Path.home() / "Desktop" / "AutoDashboard" / "apps" / "web"))
    parser.add_argument("--hour", type=int, default=18)
    parser.add_argument("--minute", type=int, default=30)
    parser.add_argument("--hourly", action="store_true", help="Run every hour at the configured minute")
    parser.add_argument("--kinds", default="wrapup,codex_rollout")
    parser.add_argument("--days-back", type=int, default=14)
    parser.add_argument("--start-at", default="")
    parser.add_argument("--focus", default="OpenClaw식 일일 회고와 다음 세션 첫 TODO 정리")
    args = parser.parse_args()

    if not args.install and not args.uninstall:
        parser.print_help()
        return 1

    system = platform.system()
    if system != "Darwin":
        print(f"Unsupported platform for this installer: {system}")
        return 1

    if args.install:
        start_at = args.start_at.strip()
        if not start_at and not args.hourly:
            start_at = "2026-03-13T18:30:00+09:00"
        plist_path = install_macos(
            autodashboard_root=Path(args.autodashboard_root).expanduser().resolve(),
            hour=args.hour,
            minute=args.minute,
            hourly=bool(args.hourly),
            kinds=args.kinds.strip() or "wrapup,codex_rollout",
            days_back=max(1, args.days_back),
            start_at=start_at,
            focus=args.focus.strip() or "OpenClaw식 일일 회고와 다음 세션 첫 TODO 정리",
            codex_command=resolve_codex_command(),
            dry_run=args.dry_run,
        )
        print(plist_path)
        return 0

    plist_path = uninstall_macos(dry_run=args.dry_run)
    print(plist_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
