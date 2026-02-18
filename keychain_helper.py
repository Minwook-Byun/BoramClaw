#!/usr/bin/env python3
from __future__ import annotations

import platform
import subprocess


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise NotImplementedError("Keychain helper is supported only on macOS.")


def store_api_key(service: str, account: str, password: str) -> None:
    _require_macos()
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            account,
            "-s",
            service,
            "-w",
            password,
            "-U",
        ],
        check=True,
    )


def load_api_key(service: str, account: str) -> str:
    _require_macos()
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            account,
            "-s",
            service,
            "-w",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()

