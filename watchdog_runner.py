#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_line(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_utc_now()} {message}\n"
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write(line)


def _get_int_env(name: str, default: int, minimum: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _sleep_with_stop(seconds: int, stop_file: Path) -> bool:
    for _ in range(seconds):
        if stop_file.exists():
            return True
        time.sleep(1)
    return stop_file.exists()


def _check_health(url: str, timeout_seconds: int) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("status", "")).lower() == "ok"
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def _append_metric(metrics_file: Path, payload: dict) -> None:
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utc_now(), **payload}
    with metrics_file.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_feedback(feedback_file: Path, payload: dict) -> None:
    feedback_file.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utc_now(), **payload}
    with feedback_file.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _emit_alert(alert_file: Path, event: str, payload: dict) -> None:
    alert_file.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utc_now(), "event": event, **payload}
    with alert_file.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_dotenv(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        data[key] = value
    return data


def _upsert_dotenv(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _resolve_under_workdir(workdir: Path, rel_path: str) -> Path:
    candidate = Path(rel_path)
    if not candidate.is_absolute():
        candidate = (workdir / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError as exc:
        raise ValueError(f"path escapes watchdog workdir: {rel_path}") from exc
    return candidate


def _port_is_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _find_free_port(start_port: int, host: str = "127.0.0.1", max_tries: int = 100) -> int | None:
    start = max(1024, int(start_port))
    for port in range(start, start + max_tries):
        if not _port_is_open(port, host=host):
            return port
    return None


def _extract_missing_packages(text: str) -> list[str]:
    missing: list[str] = []
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("❌ "):
            pkg = trimmed.replace("❌", "", 1).strip()
            if pkg and pkg not in missing:
                missing.append(pkg)
    m = re.search(r"Missing packages:\s*(.+)", text)
    if m:
        for pkg in [x.strip() for x in m.group(1).split(",")]:
            if pkg and pkg not in missing:
                missing.append(pkg)
    return missing


def _collect_guardian_report(workdir: Path, target_script: Path, stop_file: Path, health_url: str) -> dict:
    dotenv_path = workdir / ".env"
    dotenv = _parse_dotenv(dotenv_path)
    issues: list[dict] = []
    actions: list[dict] = []

    if not target_script.exists():
        issues.append({"code": "target_missing", "severity": "critical", "message": f"target missing: {target_script}"})

    required_dirs = ["logs", "schedules", "tasks", "tools"]
    for d in required_dirs:
        p = workdir / d
        if not p.exists():
            issues.append({"code": "missing_runtime_dir", "severity": "warning", "message": f"missing directory: {d}"})
            actions.append({"type": "create_dir", "path": d})

    if stop_file.exists():
        try:
            rel = str(stop_file.resolve().relative_to(workdir))
        except Exception:
            rel = str(stop_file)
        issues.append({"code": "stop_file_present", "severity": "warning", "message": f"stop file exists: {rel}"})
        actions.append({"type": "remove_file", "path": rel})

    api_key = (os.getenv("ANTHROPIC_API_KEY") or dotenv.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        issues.append({"code": "missing_api_key", "severity": "critical", "message": "ANTHROPIC_API_KEY is missing"})

    dep_missing: list[str] = []
    dep_script = workdir / "check_dependencies.py"
    if dep_script.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(dep_script)],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0:
                out = (proc.stdout or "") + "\n" + (proc.stderr or "")
                dep_missing = _extract_missing_packages(out)
                if dep_missing:
                    issues.append(
                        {
                            "code": "missing_dependencies",
                            "severity": "warning",
                            "message": f"missing dependencies: {', '.join(dep_missing)}",
                            "packages": dep_missing,
                        }
                    )
                    venv_python = workdir / ".venv/bin/python"
                    if venv_python.exists():
                        actions.append(
                            {
                                "type": "pip_install",
                                "python": str(venv_python),
                                "packages": dep_missing,
                            }
                        )
        except Exception as exc:
            issues.append({"code": "dependency_check_failed", "severity": "warning", "message": str(exc)})

    if health_url:
        parsed = urlparse(health_url)
        port = int(parsed.port or 0)
        if port > 0:
            health_ok = _check_health(health_url, timeout_seconds=2)
            if _port_is_open(port) and not health_ok:
                issues.append(
                    {
                        "code": "health_port_busy_unhealthy",
                        "severity": "warning",
                        "message": f"port {port} is open but health check failed: {health_url}",
                    }
                )
                free_port = _find_free_port(port + 1)
                if free_port is not None:
                    actions.append({"type": "set_env", "key": "HEALTH_PORT", "value": str(free_port)})
                    actions.append({"type": "set_env", "key": "WATCHDOG_HEALTH_URL", "value": f"http://127.0.0.1:{free_port}/health"})

    return {
        "tier": "level3_guardian",
        "issues": issues,
        "recommended_actions": actions,
    }


def _safe_json_extract(text: str) -> dict | None:
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _normalize_recovery_actions(actions: object) -> list[dict]:
    if not isinstance(actions, list):
        return []
    normalized: list[dict] = []
    allowed = {"create_dir", "remove_file", "set_env", "pip_install"}
    for item in actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type", "")).strip()
        if action_type not in allowed:
            continue
        normalized.append(item)
    return normalized


def _diagnose_with_llm(workdir: Path, log_path: Path, guardian_report: dict) -> dict | None:
    api_key = (os.getenv("ANTHROPIC_API_KEY") or _parse_dotenv(workdir / ".env").get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return None
    model = (os.getenv("WATCHDOG_DIAG_MODEL") or "claude-haiku-4-5-20251001").strip()
    if not model:
        return None

    tail = ""
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").splitlines()
        tail = "\n".join(lines[-80:])

    prompt = (
        "You are a recovery diagnoser for BoramClaw watchdog.\n"
        "Analyze the crash pattern and guardian report, then return strict JSON only.\n"
        "Allowed action types: create_dir(path), remove_file(path), set_env(key,value), pip_install(python,packages).\n"
        f"Guardian report:\n{json.dumps(guardian_report, ensure_ascii=False)}\n\n"
        f"Watchdog tail log:\n{tail}\n\n"
        'Return JSON: {"root_cause":"...", "confidence":0.0, "actions":[...]}'
    )

    conn = http.client.HTTPSConnection("api.anthropic.com", timeout=30)
    payload = {
        "model": model,
        "max_tokens": 700,
        "messages": [{"role": "user", "content": prompt}],
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        conn.request(
            "POST",
            "/v1/messages",
            body=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        if resp.status != 200:
            return None
        parsed = None
        # Anthropic content block extraction first.
        try:
            data = json.loads(raw)
            blocks = data.get("content", [])
            text = "".join(
                str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"
            )
            parsed = _safe_json_extract(text)
        except Exception:
            parsed = None
        if parsed is None:
            parsed = _safe_json_extract(raw)
        if parsed is None:
            return None
        if "root_cause" not in parsed and "actions" not in parsed:
            return None
        parsed["actions"] = _normalize_recovery_actions(parsed.get("actions"))
        return parsed
    except Exception:
        return None
    finally:
        conn.close()


def _apply_safe_actions(workdir: Path, actions: list[dict]) -> list[dict]:
    results: list[dict] = []
    dotenv_path = workdir / ".env"
    for action in actions:
        action_type = str(action.get("type", "")).strip()
        result: dict = {"action": action, "ok": False}
        try:
            if action_type == "create_dir":
                target = _resolve_under_workdir(workdir, str(action.get("path", "")))
                target.mkdir(parents=True, exist_ok=True)
                result["ok"] = True
            elif action_type == "remove_file":
                target = _resolve_under_workdir(workdir, str(action.get("path", "")))
                if target.exists() and target.is_file():
                    target.unlink()
                result["ok"] = True
            elif action_type == "set_env":
                key = str(action.get("key", "")).strip()
                value = str(action.get("value", "")).strip()
                if not key:
                    raise ValueError("set_env action requires key")
                _upsert_dotenv(dotenv_path, key, value)
                result["ok"] = True
            elif action_type == "pip_install":
                packages = action.get("packages")
                if not isinstance(packages, list):
                    raise ValueError("pip_install action requires packages list")
                pkg_list = [str(p).strip() for p in packages if str(p).strip()]
                if not pkg_list:
                    raise ValueError("pip_install packages list is empty")
                python_bin = str(action.get("python", "")).strip() or str(workdir / ".venv/bin/python")
                py_path = Path(python_bin)
                if not py_path.exists():
                    raise ValueError(f"python binary not found: {python_bin}")
                cmd = [str(py_path), "-m", "pip", "install", *pkg_list]
                proc = subprocess.run(
                    cmd,
                    cwd=str(workdir),
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                result["exit_code"] = proc.returncode
                result["stdout"] = (proc.stdout or "")[-800:]
                result["stderr"] = (proc.stderr or "")[-800:]
                result["ok"] = proc.returncode == 0
            else:
                result["error"] = f"unsupported action type: {action_type}"
        except Exception as exc:
            result["error"] = str(exc)
        results.append(result)
    return results


def _run_emergency_recovery(
    workdir: Path,
    log_path: Path,
    guardian_report: dict,
    auto_fix: bool,
    llm_diag_enabled: bool,
) -> dict:
    diagnosis = None
    if llm_diag_enabled:
        diagnosis = _diagnose_with_llm(workdir, log_path, guardian_report)

    planned = list(guardian_report.get("recommended_actions", []))
    if diagnosis and isinstance(diagnosis, dict):
        planned.extend(_normalize_recovery_actions(diagnosis.get("actions")))

    applied: list[dict] = []
    if auto_fix and planned:
        # Deduplicate by JSON signature.
        dedup: list[dict] = []
        seen: set[str] = set()
        for action in planned:
            sig = json.dumps(action, ensure_ascii=False, sort_keys=True)
            if sig in seen:
                continue
            seen.add(sig)
            dedup.append(action)
        applied = _apply_safe_actions(workdir, dedup)

    success = bool(applied) and all(bool(x.get("ok")) for x in applied)
    return {
        "tier": "level4_emergency",
        "diagnosis": diagnosis or {"root_cause": "heuristic-only", "confidence": 0.0, "actions": []},
        "planned_actions": planned,
        "applied_actions": applied,
        "success": success,
    }


def run_watchdog(target_script: Path) -> int:
    workdir = Path((os.getenv("WATCHDOG_WORKDIR") or ".").strip()).resolve()
    log_path = (workdir / (os.getenv("WATCHDOG_LOG_FILE") or "logs/watchdog.log").strip()).resolve()
    stop_file = (workdir / (os.getenv("WATCHDOG_STOP_FILE") or "logs/watchdog.stop").strip()).resolve()
    pid_file = (workdir / (os.getenv("WATCHDOG_PID_FILE") or "logs/watchdog.pid").strip()).resolve()

    restart_backoff = _get_int_env("WATCHDOG_RESTART_BACKOFF_SECONDS", default=3, minimum=1)
    max_backoff = _get_int_env("WATCHDOG_MAX_BACKOFF_SECONDS", default=60, minimum=1)
    min_uptime = _get_int_env("WATCHDOG_MIN_UPTIME_SECONDS", default=20, minimum=1)
    max_restarts = _get_int_env("WATCHDOG_MAX_RESTARTS", default=0, minimum=0)
    health_url = (os.getenv("WATCHDOG_HEALTH_URL") or "").strip()
    health_timeout = _get_int_env("WATCHDOG_HEALTH_TIMEOUT_SECONDS", default=2, minimum=1)
    health_fail_threshold = _get_int_env("WATCHDOG_HEALTH_FAILURE_THRESHOLD", default=3, minimum=1)
    health_check_interval = _get_int_env("WATCHDOG_HEALTH_CHECK_INTERVAL_SECONDS", default=5, minimum=1)
    health_grace = _get_int_env("WATCHDOG_HEALTH_GRACE_SECONDS", default=20, minimum=1)
    guardian_interval = _get_int_env("WATCHDOG_GUARDIAN_INTERVAL_SECONDS", default=180, minimum=15)
    emergency_threshold = _get_int_env("WATCHDOG_EMERGENCY_RESTART_THRESHOLD", default=3, minimum=1)
    metrics_file = (workdir / (os.getenv("WATCHDOG_RECOVERY_METRICS_FILE") or "logs/recovery_metrics.jsonl").strip()).resolve()
    feedback_file = (workdir / (os.getenv("WATCHDOG_FEEDBACK_FILE") or "logs/self_heal_feedback.jsonl").strip()).resolve()
    alert_file = (workdir / (os.getenv("WATCHDOG_ALERT_FILE") or "logs/recovery_alerts.jsonl").strip()).resolve()
    auto_fix = _bool_env("WATCHDOG_AUTO_FIX", False)
    llm_diag_enabled = _bool_env("WATCHDOG_LLM_DIAG_ENABLED", True)

    target_args = (os.getenv("WATCHDOG_TARGET_ARGS") or "").strip().split()

    if stop_file.exists():
        stop_file.unlink()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    env = os.environ.copy()
    env.setdefault("AGENT_MODE", "daemon")

    restart_count = 0
    consecutive_failures = 0
    backoff_seconds = restart_backoff
    _log_line(log_path, f"[watchdog] started pid={os.getpid()} target={target_script} cwd={workdir}")
    _log_line(
        log_path,
        (
            f"[watchdog] 4-tier enabled auto_fix={auto_fix} llm_diag={llm_diag_enabled} "
            f"guardian_interval={guardian_interval}s emergency_threshold={emergency_threshold}"
        ),
    )

    try:
        while True:
            if stop_file.exists():
                _log_line(log_path, "[watchdog] stop file detected before launch; exiting")
                break

            cmd = [sys.executable, str(target_script)] + target_args
            started_at = time.monotonic()
            _log_line(log_path, f"[watchdog] launching: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, cwd=str(workdir), env=env)
            health_failures = 0
            next_health_check = started_at + health_grace
            next_guardian_check = started_at + guardian_interval

            while True:
                if stop_file.exists():
                    _log_line(log_path, f"[watchdog] stop requested; terminating child pid={proc.pid}")
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                    _log_line(log_path, "[watchdog] child terminated; exiting")
                    return 0

                rc = proc.poll()
                if rc is not None:
                    uptime = int(time.monotonic() - started_at)
                    _log_line(log_path, f"[watchdog] child exited rc={rc} uptime={uptime}s")
                    _append_metric(
                        metrics_file,
                        {"event": "process_exit", "exit_code": rc, "uptime_seconds": uptime, "restart_count": restart_count},
                    )
                    if rc == 0:
                        consecutive_failures = 0
                        _log_line(log_path, "[watchdog] child exited cleanly; not restarting")
                        return 0

                    consecutive_failures += 1
                    restart_count += 1
                    if max_restarts and restart_count > max_restarts:
                        _log_line(log_path, f"[watchdog] max restarts exceeded ({max_restarts}); exiting")
                        _emit_alert(
                            alert_file,
                            "max_restarts_exceeded",
                            {
                                "max_restarts": max_restarts,
                                "restart_count": restart_count,
                                "consecutive_failures": consecutive_failures,
                            },
                        )
                        return rc

                    guardian_report = _collect_guardian_report(
                        workdir=workdir,
                        target_script=target_script,
                        stop_file=stop_file,
                        health_url=health_url,
                    )
                    _append_feedback(
                        feedback_file,
                        {
                            "event": "guardian_report_on_exit",
                            "restart_count": restart_count,
                            "consecutive_failures": consecutive_failures,
                            **guardian_report,
                        },
                    )
                    _append_metric(
                        metrics_file,
                        {
                            "event": "guardian_report",
                            "issues": len(guardian_report.get("issues", [])),
                            "consecutive_failures": consecutive_failures,
                        },
                    )

                    if auto_fix and guardian_report.get("recommended_actions"):
                        level3_apply = _apply_safe_actions(
                            workdir=workdir,
                            actions=list(guardian_report.get("recommended_actions", [])),
                        )
                        _append_feedback(
                            feedback_file,
                            {
                                "event": "guardian_autofix",
                                "restart_count": restart_count,
                                "results": level3_apply,
                            },
                        )
                        _append_metric(
                            metrics_file,
                            {
                                "event": "guardian_autofix",
                                "ok_count": sum(1 for x in level3_apply if x.get("ok")),
                                "total": len(level3_apply),
                            },
                        )

                    if consecutive_failures >= emergency_threshold:
                        emergency = _run_emergency_recovery(
                            workdir=workdir,
                            log_path=log_path,
                            guardian_report=guardian_report,
                            auto_fix=auto_fix,
                            llm_diag_enabled=llm_diag_enabled,
                        )
                        _append_feedback(
                            feedback_file,
                            {
                                "event": "emergency_recovery",
                                "restart_count": restart_count,
                                "consecutive_failures": consecutive_failures,
                                **emergency,
                            },
                        )
                        _append_metric(
                            metrics_file,
                            {
                                "event": "emergency_recovery",
                                "success": bool(emergency.get("success")),
                                "consecutive_failures": consecutive_failures,
                            },
                        )
                        if emergency.get("success"):
                            consecutive_failures = 0
                        else:
                            _emit_alert(
                                alert_file,
                                "emergency_recovery_failed",
                                {
                                    "restart_count": restart_count,
                                    "consecutive_failures": consecutive_failures,
                                    "diagnosis": emergency.get("diagnosis", {}),
                                },
                            )

                    if uptime >= min_uptime:
                        backoff_seconds = restart_backoff
                        consecutive_failures = 0
                    else:
                        backoff_seconds = min(max_backoff, max(backoff_seconds * 2, restart_backoff))

                    _log_line(
                        log_path,
                        f"[watchdog] restarting in {backoff_seconds}s (restart_count={restart_count})",
                    )
                    _append_metric(
                        metrics_file,
                        {
                            "event": "restart_scheduled",
                            "restart_count": restart_count,
                            "backoff_seconds": backoff_seconds,
                        },
                    )
                    if _sleep_with_stop(backoff_seconds, stop_file):
                        _log_line(log_path, "[watchdog] stop requested during backoff; exiting")
                        return 0
                    break

                if time.monotonic() >= next_guardian_check:
                    next_guardian_check = time.monotonic() + guardian_interval
                    guardian_report = _collect_guardian_report(
                        workdir=workdir,
                        target_script=target_script,
                        stop_file=stop_file,
                        health_url=health_url,
                    )
                    if guardian_report.get("issues"):
                        _append_feedback(
                            feedback_file,
                            {
                                "event": "guardian_periodic",
                                "restart_count": restart_count,
                                "consecutive_failures": consecutive_failures,
                                **guardian_report,
                            },
                        )
                        _append_metric(
                            metrics_file,
                            {
                                "event": "guardian_periodic",
                                "issues": len(guardian_report.get("issues", [])),
                            },
                        )
                        if auto_fix and guardian_report.get("recommended_actions"):
                            level3_apply = _apply_safe_actions(
                                workdir=workdir,
                                actions=list(guardian_report.get("recommended_actions", [])),
                            )
                            _append_feedback(
                                feedback_file,
                                {
                                    "event": "guardian_periodic_autofix",
                                    "restart_count": restart_count,
                                    "results": level3_apply,
                                },
                            )

                if health_url and time.monotonic() >= next_health_check:
                    next_health_check = time.monotonic() + health_check_interval
                    healthy = _check_health(health_url, timeout_seconds=health_timeout)
                    if healthy:
                        health_failures = 0
                    else:
                        health_failures += 1
                        _log_line(
                            log_path,
                            f"[watchdog] health check failed ({health_failures}/{health_fail_threshold}) url={health_url}",
                        )
                        if health_failures >= health_fail_threshold:
                            _log_line(log_path, "[watchdog] health threshold exceeded; restarting child")
                            _append_metric(
                                metrics_file,
                                {
                                    "event": "health_restart",
                                    "health_url": health_url,
                                    "failures": health_failures,
                                },
                            )
                            proc.terminate()
                            try:
                                proc.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=5)
                            continue
                time.sleep(1)
    finally:
        if pid_file.exists():
            pid_file.unlink()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Local watchdog runner for main.py daemon mode")
    parser.add_argument("--target", default="main.py", help="target script path (default: main.py)")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        print(f"watchdog target not found: {target}", file=sys.stderr)
        return 1
    return run_watchdog(target_script=target)


if __name__ == "__main__":
    raise SystemExit(main())
