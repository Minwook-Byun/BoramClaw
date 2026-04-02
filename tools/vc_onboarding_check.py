from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.service import get_registry, request_json, resolve_workdir


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_onboarding_check",
    "description": "Run a non-developer friendly onboarding validation checklist for VC mode.",
    "version": __version__,
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "startup_id": {"type": "string"},
            "run_sample_collect": {"type": "boolean", "default": True},
            "sample_period": {"type": "string", "default": "today"},
        },
        "required": ["startup_id"],
    },
}


def _run_json_command(cmd: list[str], *, cwd: str) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    output = (proc.stdout or "").strip()
    if not output:
        raise RuntimeError(f"empty command output: {' '.join(cmd)}")
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        parsed = json.loads(lines[-1])
    if not isinstance(parsed, dict):
        raise RuntimeError("tool output must be JSON object")
    return parsed


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    startup_id = str(input_data.get("startup_id", "")).strip().lower()
    if not startup_id:
        return {"success": False, "error": "startup_id is required"}
    run_sample_collect = bool(input_data.get("run_sample_collect", True))
    sample_period = str(input_data.get("sample_period", "today")).strip().lower() or "today"
    workdir = resolve_workdir(context)
    registry = get_registry(context)

    checks: list[dict[str, Any]] = []
    tenant = registry.get(startup_id)
    if tenant is None:
        return {"success": False, "error": f"tenant not found: {startup_id}"}
    checks.append({"name": "tenant_registered", "ok": True, "detail": startup_id})

    gateway_url = str(tenant.get("gateway_url", "")).strip()
    if not gateway_url:
        return {"success": False, "error": "tenant gateway_url is empty"}
    try:
        health = request_json(method="GET", url=gateway_url.rstrip("/") + "/health", timeout=10)
        ok = bool(health.get("ok", False))
        checks.append({"name": "gateway_health", "ok": ok, "detail": gateway_url})
        if not ok:
            return {"success": False, "error": "gateway health check failed", "checks": checks}
    except Exception as exc:
        checks.append({"name": "gateway_health", "ok": False, "detail": str(exc)})
        return {"success": False, "error": f"gateway health check failed: {exc}", "checks": checks}

    collect_result: dict[str, Any] = {}
    report_result: dict[str, Any] = {}
    if run_sample_collect:
        collect_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "vc_collect_bundle.py"),
            "--tool-input-json",
            json.dumps(
                {
                    "action": "collect",
                    "startup_id": startup_id,
                    "period": sample_period,
                    "include_ocr": True,
                    "max_artifacts": 100,
                    "auto_verify": True,
                }
            ),
            "--tool-context-json",
            json.dumps({"workdir": str(workdir)}),
        ]
        collect_result = _run_json_command(collect_cmd, cwd=str(PROJECT_ROOT))
        checks.append(
            {
                "name": "sample_collect",
                "ok": bool(collect_result.get("success", False)),
                "detail": str(collect_result.get("collection_id", "")),
            }
        )
        if not bool(collect_result.get("success", False)):
            return {"success": False, "error": "sample collect failed", "checks": checks, "collect": collect_result}

        report_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "vc_generate_report.py"),
            "--tool-input-json",
            json.dumps(
                {
                    "startup_id": startup_id,
                    "mode": "daily",
                    "output_file": f"logs/onboarding_{startup_id}_daily_report.md",
                }
            ),
            "--tool-context-json",
            json.dumps({"workdir": str(workdir)}),
        ]
        report_result = _run_json_command(report_cmd, cwd=str(PROJECT_ROOT))
        checks.append(
            {
                "name": "sample_report",
                "ok": bool(report_result.get("success", False)),
                "detail": str(report_result.get("output_file", "")),
            }
        )

    success = all(bool(row.get("ok", False)) for row in checks)
    return {
        "success": success,
        "startup_id": startup_id,
        "checks": checks,
        "collect": collect_result,
        "report": report_result,
        "next_steps": [
            f"/vc scope {startup_id}",
            f"/vc collect {startup_id} 7d",
            f"/vc dashboard {startup_id} 30d",
        ],
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_onboarding_check cli")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()
    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0
        input_data = _load_json_object(args.tool_input_json)
        context = _load_json_object(args.tool_context_json)
        result = run(input_data, context)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
