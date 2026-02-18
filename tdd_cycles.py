#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_once() -> tuple[int, float, str]:
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - started
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, duration, output.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run unittest cycles and log per-cycle results.")
    parser.add_argument("cycles", nargs="?", type=int, default=10)
    parser.add_argument("--log-file", default="logs/tdd_cycles.jsonl")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    cycles = max(1, int(args.cycles))
    log_path = Path(args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    any_fail = False
    for i in range(1, cycles + 1):
        rc, duration, output = run_once()
        record = {
            "ts": now_iso(),
            "cycle": i,
            "exit_code": rc,
            "duration_sec": round(duration, 3),
            "ok": rc == 0,
            "output_preview": output[:1000],
        }
        if args.label:
            record["label"] = args.label
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        label_text = f" label={args.label}" if args.label else ""
        print(f"[TDD]{label_text} cycle={i} rc={rc} duration={duration:.2f}s")
        if rc != 0:
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
