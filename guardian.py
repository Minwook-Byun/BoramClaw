from __future__ import annotations

import ast
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any


def _port_is_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, int(port))) == 0


def _find_free_port(start_port: int, host: str = "127.0.0.1", max_tries: int = 200) -> int | None:
    start = max(1024, int(start_port))
    for port in range(start, start + max_tries):
        if not _port_is_open(port, host=host):
            return port
    return None


def _extract_missing_packages(output: str) -> list[str]:
    missing: list[str] = []
    for line in output.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("❌ "):
            pkg = trimmed.replace("❌", "", 1).strip()
            if pkg and pkg not in missing:
                missing.append(pkg)
    marker = "Missing packages:"
    if marker in output:
        tail = output.split(marker, 1)[1]
        for pkg in [x.strip() for x in tail.splitlines()[0].split(",")]:
            if pkg and pkg not in missing:
                missing.append(pkg)
    return missing


def _safe_relpath(base: Path, target: Path) -> str:
    try:
        return str(target.resolve().relative_to(base.resolve()))
    except Exception:
        return str(target)


def _read_required_packages(dep_script: Path) -> list[str]:
    try:
        source = dep_script.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(dep_script))
    except Exception:
        return []

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "REQUIRED_PACKAGES":
                value = node.value
                if not isinstance(value, (ast.List, ast.Tuple)):
                    continue
                packages: list[str] = []
                for elt in value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        pkg = elt.value.strip()
                        if pkg:
                            packages.append(pkg)
                return packages
    return []


@dataclass
class GuardianIssue:
    code: str
    severity: str
    message: str
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


def run_guardian_preflight(
    config: Any,
    check_dependencies: bool = True,
    auto_fix: bool = False,
    auto_install_deps: bool = False,
) -> dict[str, Any]:
    workdir = Path(str(getattr(config, "tool_workdir", ".")).strip() or ".").expanduser().resolve()
    issues: list[GuardianIssue] = []
    planned_actions: list[dict[str, Any]] = []
    applied_actions: list[dict[str, Any]] = []

    runtime_dirs = [
        workdir / "logs",
        workdir / "schedules",
        workdir / "tasks",
    ]
    custom_tool_dir = Path(str(getattr(config, "custom_tool_dir", "tools")).strip() or "tools")
    if not custom_tool_dir.is_absolute():
        custom_tool_dir = (workdir / custom_tool_dir).resolve()
    runtime_dirs.append(custom_tool_dir)

    for path in runtime_dirs:
        if not path.exists():
            rel = _safe_relpath(workdir, path)
            issues.append(
                GuardianIssue(
                    code="missing_runtime_dir",
                    severity="warning",
                    message=f"런타임 디렉토리가 없습니다: {rel}",
                    detail={"path": rel},
                )
            )
            planned_actions.append({"type": "create_dir", "path": rel})

    if bool(getattr(config, "health_server_enabled", False)):
        port = int(getattr(config, "health_port", 0) or 0)
        if port > 0 and _port_is_open(port):
            issues.append(
                GuardianIssue(
                    code="health_port_conflict",
                    severity="warning",
                    message=f"HEALTH_PORT({port})가 이미 사용 중입니다.",
                    detail={"port": port},
                )
            )
            free_port = _find_free_port(port + 1)
            if free_port is not None:
                planned_actions.append({"type": "set_health_port", "value": int(free_port)})

    if check_dependencies:
        dep_script = workdir / "check_dependencies.py"
        if dep_script.exists():
            required_packages = _read_required_packages(dep_script)
            if required_packages:
                missing: list[str] = []
                for pkg in required_packages:
                    mod_name = pkg.replace("-", "_")
                    try:
                        importlib.import_module(mod_name)
                    except Exception:
                        missing.append(pkg)
                if missing:
                    issues.append(
                        GuardianIssue(
                            code="missing_dependencies",
                            severity="warning",
                            message=f"누락 의존성: {', '.join(missing)}",
                            detail={"packages": missing},
                        )
                    )
                    if auto_install_deps:
                        planned_actions.append({"type": "pip_install", "packages": missing})
            else:
                try:
                    proc = subprocess.run(
                        [sys.executable, str(dep_script)],
                        cwd=str(workdir),
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if proc.returncode != 0:
                        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
                        missing = _extract_missing_packages(combined)
                        if missing:
                            issues.append(
                                GuardianIssue(
                                    code="missing_dependencies",
                                    severity="warning",
                                    message=f"누락 의존성: {', '.join(missing)}",
                                    detail={"packages": missing},
                                )
                            )
                            if auto_install_deps:
                                planned_actions.append({"type": "pip_install", "packages": missing})
                        else:
                            issues.append(
                                GuardianIssue(
                                    code="dependency_check_failed",
                                    severity="warning",
                                    message="의존성 점검 실패(패키지 목록 파악 불가)",
                                )
                            )
                except Exception as exc:
                    issues.append(
                        GuardianIssue(
                            code="dependency_check_exception",
                            severity="warning",
                            message=f"의존성 점검 중 예외: {exc}",
                        )
                    )

    if auto_fix:
        for action in planned_actions:
            action_type = str(action.get("type", "")).strip()
            result: dict[str, Any] = {"action": action, "ok": False}
            try:
                if action_type == "create_dir":
                    rel = str(action.get("path", "")).strip()
                    target = (workdir / rel).resolve()
                    target.relative_to(workdir)
                    target.mkdir(parents=True, exist_ok=True)
                    result["ok"] = True
                elif action_type == "set_health_port":
                    new_port = int(action.get("value", 0) or 0)
                    if new_port <= 0:
                        raise ValueError("유효하지 않은 포트 값")
                    setattr(config, "health_port", new_port)
                    result["ok"] = True
                elif action_type == "pip_install":
                    packages = action.get("packages")
                    if not isinstance(packages, list):
                        raise ValueError("packages 형식이 올바르지 않습니다.")
                    pkg_list = [str(x).strip() for x in packages if str(x).strip()]
                    if not pkg_list:
                        raise ValueError("설치할 패키지가 비어 있습니다.")
                    proc = subprocess.run(
                        [sys.executable, "-m", "pip", "install", *pkg_list],
                        cwd=str(workdir),
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    result["exit_code"] = int(proc.returncode)
                    result["ok"] = proc.returncode == 0
                    result["stdout"] = (proc.stdout or "")[-800:]
                    result["stderr"] = (proc.stderr or "")[-800:]
                else:
                    result["error"] = f"지원하지 않는 액션입니다: {action_type}"
            except Exception as exc:
                result["error"] = str(exc)
            applied_actions.append(result)

    validation_errors = []
    validate_fn = getattr(config, "validate", None)
    if callable(validate_fn):
        try:
            candidate = validate_fn()
            if isinstance(candidate, list):
                validation_errors = [str(x) for x in candidate if str(x).strip()]
        except Exception as exc:
            validation_errors = [f"설정 검증 실행 실패: {exc}"]

    for message in validation_errors:
        issues.append(
            GuardianIssue(
                code="config_validation_error",
                severity="critical",
                message=message,
            )
        )

    issue_dicts = [x.as_dict() for x in issues]
    critical_count = sum(1 for x in issue_dicts if str(x.get("severity", "")).lower() == "critical")
    warning_count = sum(1 for x in issue_dicts if str(x.get("severity", "")).lower() == "warning")
    return {
        "ok": critical_count == 0,
        "issue_count": len(issue_dicts),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "issues": issue_dicts,
        "planned_actions": planned_actions,
        "applied_actions": applied_actions,
        "workdir": str(workdir),
    }


def format_guardian_report(report: dict[str, Any]) -> str:
    issue_count = int(report.get("issue_count", 0) or 0)
    critical_count = int(report.get("critical_count", 0) or 0)
    warning_count = int(report.get("warning_count", 0) or 0)
    lines = [
        f"[Guardian] preflight 결과: issues={issue_count}, critical={critical_count}, warning={warning_count}",
    ]
    for item in report.get("issues", []):
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity", "info")).lower()
        code = str(item.get("code", "unknown"))
        msg = str(item.get("message", ""))
        lines.append(f"- [{sev}] {code}: {msg}")

    planned = report.get("planned_actions", [])
    if isinstance(planned, list) and planned:
        lines.append("- planned_actions:")
        for action in planned:
            try:
                lines.append(f"  - {json.dumps(action, ensure_ascii=False)}")
            except Exception:
                lines.append(f"  - {action}")

    applied = report.get("applied_actions", [])
    if isinstance(applied, list) and applied:
        lines.append("- applied_actions:")
        for action in applied:
            try:
                lines.append(f"  - {json.dumps(action, ensure_ascii=False)}")
            except Exception:
                lines.append(f"  - {action}")
    return "\n".join(lines)
