#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys


REQUIRED_PACKAGES = {
    "anthropic": "anthropic",
    "google-auth": "google.oauth2",
    "google-auth-oauthlib": "google_auth_oauthlib",
    "google-api-python-client": "googleapiclient",
    "feedparser": "feedparser",
}


def check_package(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def main() -> int:
    missing: list[str] = []
    print("🔍 Checking dependencies...")
    for package_name, module_name in REQUIRED_PACKAGES.items():
        if check_package(module_name):
            print(f"  ✅ {package_name}")
        else:
            print(f"  ❌ {package_name}")
            missing.append(package_name)
    if missing:
        print(f"\n❌ Missing packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        return 1
    print("\n✅ All dependencies installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

