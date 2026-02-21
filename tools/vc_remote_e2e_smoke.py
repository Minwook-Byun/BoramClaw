from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vc_platform.crypto_store import VCCryptoStore


__version__ = "0.1.0"

TOOL_SPEC = {
    "name": "vc_remote_e2e_smoke",
    "description": "Run full remote-like VC E2E smoke loop and write report.",
    "version": __version__,
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "startup_id": {"type": "string", "default": "demo"},
            "port": {"type": "integer", "default": 18742, "minimum": 1024, "maximum": 65535},
            "base_dir": {"type": "string", "description": "Relative output root under workdir"},
            "cleanup": {"type": "boolean", "default": False},
            "report_file": {"type": "string", "description": "Optional report file path under workdir"},
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _run_json_command(cmd: list[str], *, cwd: str) -> tuple[dict[str, Any], str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    text = (proc.stdout or "").strip()
    if not text:
        raise RuntimeError(f"empty output from command: {' '.join(cmd)}")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        parsed = json.loads(lines[-1])
    if not isinstance(parsed, dict):
        raise RuntimeError(f"command output must be JSON object: {' '.join(cmd)}")
    return parsed, text


def _wait_gateway_ready(port: int, timeout_seconds: int = 15) -> None:
    started = time.time()
    while time.time() - started < timeout_seconds:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                if resp.status != 200:
                    time.sleep(0.3)
                    continue
                payload = json.loads(resp.read().decode("utf-8"))
                if isinstance(payload, dict) and bool(payload.get("ok", False)):
                    return
        except (TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.3)
    raise RuntimeError(f"gateway did not become healthy on port {port}")


def _make_report_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# VC Remote E2E Smoke Report",
        "",
        f"- Generated At (UTC): {_utc_now().isoformat()}",
        f"- Startup ID: {result.get('startup_id', '')}",
        f"- Port: {result.get('port', '')}",
        f"- Success: {result.get('success', False)}",
        "",
        "## Step Results",
    ]
    for step in result.get("steps", []):
        if not isinstance(step, dict):
            continue
        name = str(step.get("name", "step"))
        ok = bool(step.get("ok", False))
        detail = str(step.get("detail", ""))
        lines.append(f"- {'✅' if ok else '❌'} {name}: {detail}")

    lines.append("")
    lines.append("## Collect Summary")
    collect = result.get("collect", {})
    if isinstance(collect, dict):
        lines.append(f"- collection_id: {collect.get('collection_id', '')}")
        lines.append(f"- approval_id: {collect.get('approval_id', '')}")
        summary = collect.get("summary", {})
        if isinstance(summary, dict):
            lines.append(f"- artifact_count: {summary.get('artifact_count', 0)}")
            lines.append(f"- total_size_bytes: {summary.get('total_size_bytes', 0)}")
            lines.append(f"- doc_types: {json.dumps(summary.get('doc_types', {}), ensure_ascii=False)}")
        verification = collect.get("verification", {})
        if isinstance(verification, dict):
            lines.append(f"- auto_verification_success: {verification.get('success', False)}")

    lines.append("")
    lines.append("## Paths")
    lines.append(f"- simulation_root: {result.get('simulation_root', '')}")
    lines.append(f"- report_file: {result.get('report_file', '')}")
    return "\n".join(lines).strip() + "\n"


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    workdir = Path(str(context.get("workdir", ".")).strip() or ".").resolve()
    startup_id = str(input_data.get("startup_id", "demo")).strip().lower() or "demo"
    port = int(input_data.get("port", 18742) or 18742)
    port = max(1024, min(port, 65535))
    cleanup = bool(input_data.get("cleanup", False))
    base_dir = str(input_data.get("base_dir", "logs/e2e_vc_remote_smoke")).strip() or "logs/e2e_vc_remote_smoke"
    sim_root = (workdir / base_dir).resolve()
    try:
        sim_root.relative_to(workdir)
    except ValueError as exc:
        raise ValueError("base_dir must be inside workdir") from exc

    if sim_root.exists():
        shutil.rmtree(sim_root, ignore_errors=True)
    startup_root = sim_root / "startup_pc"
    central_root = sim_root / "central_vc"
    shared_dir = startup_root / "Desktop" / "common"
    shared_dir.mkdir(parents=True, exist_ok=True)
    (central_root / "config").mkdir(parents=True, exist_ok=True)
    (central_root / "data").mkdir(parents=True, exist_ok=True)
    (central_root / "vault").mkdir(parents=True, exist_ok=True)
    (central_root / "logs").mkdir(parents=True, exist_ok=True)
    (startup_root / "config").mkdir(parents=True, exist_ok=True)

    docs = {
        f"{startup_id}_business_registration.txt": "사업자등록증 사본",
        f"{startup_id}_ir_deck_q1.txt": "IR deck and product roadmap",
        f"{startup_id}_tax_invoice_202602.txt": "세금계산서 2026-02",
        f"{startup_id}_social_insurance_status.txt": "4대 보험 납부 확인",
        f"{startup_id}_investment_decision_minutes.txt": "이사회 투자 의사결정",
    }
    for name, body in docs.items():
        (shared_dir / name).write_text(body + "\n", encoding="utf-8")

    secret = "smoke-secret"
    gateway_cfg = {
        "startup_id": startup_id,
        "shared_secret": secret,
        "max_artifacts": 500,
        "folders": {"desktop_common": str(shared_dir.resolve())},
    }
    gateway_cfg_path = startup_root / "config" / "vc_gateway.json"
    gateway_cfg_path.write_text(json.dumps(gateway_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    tenant_cfg = {
        "tenants": [
            {
                "startup_id": startup_id,
                "display_name": f"{startup_id.title()} Startup",
                "gateway_url": f"http://127.0.0.1:{port}",
                "folder_alias": "desktop_common",
                "gateway_secret": secret,
                "allowed_doc_types": [
                    "business_registration",
                    "ir_deck",
                    "tax_invoice",
                    "social_insurance",
                    "investment_decision",
                ],
                "email_recipients": ["ops@vc.test"],
                "active": True,
            }
        ]
    }
    (central_root / "config" / "vc_tenants.json").write_text(
        json.dumps(tenant_cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    steps: list[dict[str, Any]] = []
    gateway_proc: subprocess.Popen[str] | None = None
    collect_payload: dict[str, Any] = {}
    pending_payload: dict[str, Any] = {}
    approve_payload: dict[str, Any] = {}
    report_payload: dict[str, Any] = {}
    try:
        gateway_proc = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                str(PROJECT_ROOT / "vc_gateway_agent.py"),
                "--config",
                str(gateway_cfg_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_gateway_ready(port)
        steps.append({"name": "gateway_start", "ok": True, "detail": f"gateway healthy on {port}"})

        collect_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "vc_collect_bundle.py"),
            "--tool-input-json",
            json.dumps({"action": "collect", "startup_id": startup_id, "period": "30d", "include_ocr": True}),
            "--tool-context-json",
            json.dumps({"workdir": str(central_root)}),
        ]
        collect_payload, _ = _run_json_command(collect_cmd, cwd=str(PROJECT_ROOT))
        collect_ok = bool(collect_payload.get("success", False))
        steps.append({"name": "collect", "ok": collect_ok, "detail": collect_payload.get("collection_id", "")})
        if not collect_ok:
            raise RuntimeError(f"collect failed: {collect_payload}")

        approval_id = str(collect_payload.get("approval_id", ""))
        if not approval_id:
            raise RuntimeError("approval_id missing after collect")

        pending_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "vc_approval_queue.py"),
            "--tool-input-json",
            json.dumps({"action": "pending", "startup_id": startup_id}),
            "--tool-context-json",
            json.dumps({"workdir": str(central_root)}),
        ]
        pending_payload, _ = _run_json_command(pending_cmd, cwd=str(PROJECT_ROOT))
        pending_ok = bool(pending_payload.get("success", False))
        steps.append({"name": "pending", "ok": pending_ok, "detail": f"count={pending_payload.get('count', 0)}"})
        if not pending_ok:
            raise RuntimeError(f"pending failed: {pending_payload}")

        approve_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "vc_approval_queue.py"),
            "--tool-input-json",
            json.dumps({"action": "approve", "approval_id": approval_id, "approver": "smoke-bot"}),
            "--tool-context-json",
            json.dumps({"workdir": str(central_root)}),
        ]
        approve_payload, _ = _run_json_command(approve_cmd, cwd=str(PROJECT_ROOT))
        approve_ok = bool(approve_payload.get("success", False))
        steps.append({"name": "approve", "ok": approve_ok, "detail": approval_id})
        if not approve_ok:
            raise RuntimeError(f"approve failed: {approve_payload}")

        out_file = "logs/smoke_weekly_report.md"
        report_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "vc_generate_report.py"),
            "--tool-input-json",
            json.dumps({"startup_id": startup_id, "mode": "weekly", "output_file": out_file}),
            "--tool-context-json",
            json.dumps({"workdir": str(central_root)}),
        ]
        report_payload, _ = _run_json_command(report_cmd, cwd=str(PROJECT_ROOT))
        report_ok = bool(report_payload.get("success", False))
        steps.append({"name": "report", "ok": report_ok, "detail": str(report_payload.get("output_file", ""))})
        if not report_ok:
            raise RuntimeError(f"report failed: {report_payload}")

        # 복호화 확인
        encrypted_rel = str(collect_payload.get("encrypted_path", ""))
        if encrypted_rel:
            envelope_file = (central_root / encrypted_rel).resolve()
            envelope = json.loads(envelope_file.read_text(encoding="utf-8"))
            store = VCCryptoStore(central_root / "data" / "vc_keys.json")
            collection_id = str(collect_payload.get("collection_id", ""))
            plaintext = store.decrypt_for_startup(startup_id, envelope, aad=collection_id.encode("utf-8"))
            payload = json.loads(plaintext.decode("utf-8"))
            artifact_count = len(payload.get("artifacts", [])) if isinstance(payload, dict) else 0
            steps.append({"name": "decrypt_verify", "ok": artifact_count >= 1, "detail": f"artifacts={artifact_count}"})

    finally:
        if gateway_proc is not None:
            gateway_proc.terminate()
            try:
                gateway_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                gateway_proc.kill()
                gateway_proc.wait(timeout=3)
        steps.append({"name": "gateway_stop", "ok": True, "detail": "stopped"})

    success = all(bool(step.get("ok", False)) for step in steps)
    report_file_input = str(input_data.get("report_file", "")).strip()
    if report_file_input:
        report_file = (workdir / report_file_input).resolve()
    else:
        report_file = (workdir / "logs" / f"vc_remote_e2e_report_{_utc_now().strftime('%Y%m%d_%H%M%S')}.md").resolve()
    try:
        report_file.relative_to(workdir)
    except ValueError as exc:
        raise ValueError("report_file must be inside workdir") from exc
    report_file.parent.mkdir(parents=True, exist_ok=True)

    result = {
        "success": success,
        "startup_id": startup_id,
        "port": port,
        "simulation_root": str(sim_root),
        "collect": collect_payload,
        "pending": pending_payload,
        "approve": approve_payload,
        "report": report_payload,
        "steps": steps,
        "generated_at": _utc_now().isoformat(),
        "report_file": str(report_file),
    }
    markdown = _make_report_markdown(result)
    report_file.write_text(markdown, encoding="utf-8")

    if cleanup:
        shutil.rmtree(sim_root, ignore_errors=True)

    return result


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="vc_remote_e2e_smoke cli")
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
