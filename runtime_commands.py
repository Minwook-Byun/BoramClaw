from __future__ import annotations

import json
import os
import re
from typing import Any

VC_PRIMARY_SUBCOMMANDS: tuple[str, ...] = (
    "register",
    "bind-folder",
    "collect",
    "report",
    "verify",
    "onboard",
    "pending",
    "approve",
    "reject",
    "status",
    "scope",
    "scope-audit",
    "dashboard",
    "help",
)

INTEGRATION_PRIMARY_SUBCOMMANDS: tuple[str, ...] = (
    "connect",
    "exchange",
    "refresh",
    "test",
    "status",
    "revoke",
    "help",
)


def is_tool_list_request(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized.startswith("/tool "):
        return False
    if normalized in {"/tools", "tools", "tool list", "도구 목록", "툴 목록", "도구리스트", "툴리스트"}:
        return True
    return any(keyword in normalized for keyword in ("tool list", "도구 목록", "툴 목록", "도구 리스트", "툴 리스트"))


def is_schedule_list_request(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in {"/schedules", "schedules", "schedule list", "스케줄 목록", "일정 목록"}:
        return True
    return any(keyword in normalized for keyword in ("schedule list", "스케줄 목록", "일정 목록"))


def format_tool_list(executor: Any) -> str:
    lines = [f"사용 가능한 도구 목록 (custom dir: {executor.custom_tool_dir}):"]
    for item in executor.describe_tools():
        required = ", ".join(item["required"]) if item["required"] else "-"
        file_hint = f", 파일: {item['file']}" if item.get("file") else ""
        lines.append(f"- {item['name']} [{item['source']}]: {item['description']} (필수: {required}{file_hint})")
    if executor.load_errors:
        lines.append("")
        lines.append("로드 실패한 커스텀 도구:")
        for err in executor.load_errors:
            lines.append(f"- {err}")
    lines.append("")
    lines.append("직접 실행 예시: /tool list_files {\"path\":\".\"}")
    lines.append("파일 읽기 예시: /tool read_text_file {\"path\":\"tools/add_two_numbers.py\"}")
    lines.append("파일 저장 예시: /tool save_text_file {\"path\":\"tools/my_tool.py\",\"content\":\"...\"}")
    lines.append("커스텀 조회 예시: /tool list_custom_tools {}")
    lines.append("파일시스템 상태 조회 예시: /tool tool_registry_status {}")
    lines.append("커스텀 삭제 예시: /tool delete_custom_tool_file {\"file_name\":\"my_tool.py\"}")
    lines.append(
        "스케줄 등록 예시: /tool schedule_daily_tool {\"tool_name\":\"echo_tool\",\"time\":\"09:00\",\"tool_input\":{\"text\":\"daily\"}}"
    )
    lines.append("스케줄 목록 예시: /schedules")
    lines.append("arXiv 일일 스케줄 예시: /schedule-arxiv 08:00 deepseek llm")
    lines.append("깊은 주간 회고 예시: 이번 주 깊이 있는 회고 작성해줘")
    lines.append("Semantic snapshot 예시: /tool semantic_web_snapshot {\"url\":\"https://arxiv.org\"}")
    lines.append("온체인 조회 예시: /tool onchain_wallet_snapshot {\"network\":\"ethereum\",\"address\":\"0x...\"}")
    lines.append("텔레그램 전송 예시: /tool telegram_send_message {\"text\":\"안녕하세요\"}")
    lines.append("VC 수집 예시: /vc collect acme 7d")
    lines.append("VC 자동검증 예시: /vc verify acme")
    lines.append("VC 스코프 정책 예시: /vc scope acme")
    lines.append("VC 대시보드 예시: /vc dashboard acme 30d")
    lines.append("VC 도움말: /vc help")
    lines.append("VC 승인 예시: /vc approve <approval_id>")
    lines.append("Integration 연결 예시: /integration connect acme google_drive")
    lines.append("Integration 상태 예시: /integration status acme")
    lines.append("Integration 도움말: /integration help")
    lines.append("재동기화 예시: /sync-tools")
    return "\n".join(lines)


def format_vc_help() -> str:
    lines = [
        "VC 수집 기능 사용법",
        "",
        "1) 초기 등록",
        "- /vc help",
        "- /vc register <startup_id> <display_name>",
        "- /vc bind-folder <startup_id> <gateway_url> <folder_alias>",
        "",
        "2) 수집/리포트",
        "- /vc collect <startup_id> <today|7d|30d>",
        "- /vc report <startup_id> <daily|weekly|range:YYYY-MM-DD,YYYY-MM-DD>",
        "- /vc verify [startup_id]",
        "- /vc onboard <startup_id> [today|7d]",
        "- /vc status <startup_id>",
        "- /vc dashboard [startup_id] [7d|30d|90d]",
        "",
        "3) 승인 게이트",
        "- /vc pending [startup_id]",
        "- /vc approve <approval_id> [force] [by=<approver>]",
        "- /vc reject <approval_id> [reason]",
        "",
        "4) 동의 범위 정책",
        "- /vc scope <startup_id>",
        "- /vc scope <startup_id> allow=<csv> deny=<csv> docs=<csv> consent=<ref> retention=<days>",
        "- /vc scope-audit <startup_id> [limit] [allow|reject]",
        "",
        "빠른 시작 예시:",
        "- /vc collect acme 7d",
        "- /vc onboard acme 7d",
        "- /vc verify acme",
        "- /vc scope acme allow=desktop_common/IR,desktop_common/Finance deny=*private*",
        "- /vc dashboard acme 30d",
        "- /vc pending acme",
        "- /vc approve 11111111-2222-3333-4444-555555555555 force by=alice",
    ]
    return "\n".join(lines)


def format_integration_help() -> str:
    lines = [
        "Integration 연동 기능 사용법 (BYO OAuth 스캐폴드)",
        "",
        "1) 연결 생성",
        "- /integration help",
        "- /integration connect <startup_id> <google_drive|google_gmail|google>",
        "- /integration connect <startup_id> <provider> client_id=<id> client_secret=<secret> scopes=<csv>",
        "",
        "2) 상태/검증",
        "- /integration exchange <connection_id> code=<auth_code> [redirect_uri=<uri>]",
        "- /integration refresh <connection_id> [force] [min_valid_seconds=<n>]",
        "- /integration status <startup_id> [provider]",
        "- /integration test <connection_id>",
        "",
        "3) 연결 해제",
        "- /integration revoke <connection_id> [reason]",
        "",
        "빠른 시작 예시:",
        "- /integration connect acme google_drive",
        "- /integration exchange 11111111-2222-3333-4444-555555555555 code=4/0AR...",
        "- /integration refresh 11111111-2222-3333-4444-555555555555 force",
        "- /integration status acme",
        "- /integration test 11111111-2222-3333-4444-555555555555",
        "- /integration revoke 11111111-2222-3333-4444-555555555555 policy_update",
    ]
    return "\n".join(lines)


def parse_tool_command(text: str) -> tuple[str, dict[str, Any]] | None:
    if not text.startswith("/tool "):
        return None
    payload = text[len("/tool ") :].strip()
    if not payload:
        raise ValueError("사용법: /tool <tool_name> <json_input(optional)>")

    parts = payload.split(maxsplit=1)
    tool_name = parts[0].strip()
    if not tool_name:
        raise ValueError("도구 이름(tool_name)은 필수입니다.")

    if len(parts) == 1:
        return tool_name, {}

    raw_json = parts[1].strip()
    if not raw_json:
        return tool_name, {}
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 입력 형식이 올바르지 않습니다: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("도구 입력 JSON은 객체(object)여야 합니다.")
    return tool_name, parsed


def parse_vc_command(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    known_subcommands = set(VC_PRIMARY_SUBCOMMANDS) | {"start", "시작", "도움말"}

    command_text = ""
    if lowered.startswith("/vc "):
        command_text = normalized[4:].strip()
    elif lowered == "/vc":
        return {"tool_name": "__vc_help__", "tool_input": {}}
    elif lowered.startswith("vc "):
        candidate = normalized[3:].strip()
        head = candidate.split(maxsplit=1)[0].strip().lower() if candidate else ""
        if head in known_subcommands:
            command_text = candidate
    elif lowered.startswith("vc:"):
        candidate = normalized[3:].strip()
        head = candidate.split(maxsplit=1)[0].strip().lower() if candidate else ""
        if head in known_subcommands:
            command_text = candidate

    if not command_text:
        # 보조 자연어 파싱 (과도한 오탐 방지 위해 VC/액셀러레이터 키워드가 있는 경우만)
        context_tokens = ("vc", "액셀러레이터", "accelerator")
        if not any(token in lowered for token in context_tokens):
            return None

        if any(token in lowered for token in ("도움", "help", "사용법", "가이드", "시작")):
            return {"tool_name": "__vc_help__", "tool_input": {}}

        # 승인/거절
        approval_match = re.search(r"\b([0-9a-f]{8}-[0-9a-f-]{27,})\b", lowered)
        if approval_match and any(token in lowered for token in ("approve", "승인")):
            return {
                "tool_name": "vc_approval_queue",
                "tool_input": {"action": "approve", "approval_id": approval_match.group(1)},
            }
        if approval_match and any(token in lowered for token in ("reject", "거절")):
            return {
                "tool_name": "vc_approval_queue",
                "tool_input": {"action": "reject", "approval_id": approval_match.group(1), "reason": "manual reject"},
            }

        # 수집
        if any(token in lowered for token in ("collect", "수집")):
            startup_candidates = re.findall(r"\b([a-z0-9][a-z0-9_-]{1,63})\b", lowered)
            excluded_tokens = {
                "vc",
                "collect",
                "today",
                "week",
                "daily",
                "weekly",
                "accelerator",
            }
            startup_id = ""
            for candidate in startup_candidates:
                if candidate in excluded_tokens:
                    continue
                if candidate.isdigit():
                    continue
                startup_id = candidate
                break
            days_match = re.search(r"\b(\d+)\s*(d|day|days|일)\b", lowered)
            period = "7d"
            if "today" in lowered or "오늘" in normalized:
                period = "today"
            elif days_match:
                period = f"{max(1, min(int(days_match.group(1)), 365))}d"
            if startup_id:
                return {
                    "tool_name": "vc_collect_bundle",
                    "tool_input": {"action": "collect", "startup_id": startup_id, "period": period},
                }
        return None

    parts = command_text.split()
    sub = parts[0].strip().lower()
    args = parts[1:]

    if sub in {"help", "start", "시작", "도움말"}:
        return {"tool_name": "__vc_help__", "tool_input": {}}

    if sub == "register":
        if len(args) < 2:
            raise ValueError("사용법: /vc register <startup_id> <display_name>")
        startup_id = args[0].strip().lower()
        display_name = " ".join(args[1:]).strip()
        return {
            "tool_name": "vc_collect_bundle",
            "tool_input": {
                "action": "register",
                "startup_id": startup_id,
                "display_name": display_name,
            },
        }

    if sub == "bind-folder":
        if len(args) < 3:
            raise ValueError("사용법: /vc bind-folder <startup_id> <gateway_url> <folder_alias> [gateway_secret]")
        startup_id = args[0].strip().lower()
        gateway_url = args[1].strip()
        folder_alias = args[2].strip()
        tool_input: dict[str, Any] = {
            "action": "bind_folder",
            "startup_id": startup_id,
            "gateway_url": gateway_url,
            "folder_alias": folder_alias,
        }
        if len(args) >= 4 and args[3].strip():
            tool_input["gateway_secret"] = args[3].strip()
        return {"tool_name": "vc_collect_bundle", "tool_input": tool_input}

    if sub == "collect":
        if len(args) < 1:
            raise ValueError("사용법: /vc collect <startup_id> <today|7d|30d>")
        startup_id = args[0].strip().lower()
        period = args[1].strip().lower() if len(args) >= 2 else "7d"
        return {
            "tool_name": "vc_collect_bundle",
            "tool_input": {"action": "collect", "startup_id": startup_id, "period": period},
        }

    if sub == "report":
        if len(args) < 1:
            raise ValueError("사용법: /vc report <startup_id> <daily|weekly|range:YYYY-MM-DD,YYYY-MM-DD>")
        startup_id = args[0].strip().lower()
        mode = args[1].strip() if len(args) >= 2 else "weekly"
        return {
            "tool_name": "vc_generate_report",
            "tool_input": {"startup_id": startup_id, "mode": mode},
        }

    if sub == "verify":
        startup_id = args[0].strip().lower() if args else "demo"
        return {
            "tool_name": "vc_remote_e2e_smoke",
            "tool_input": {"startup_id": startup_id},
        }

    if sub == "onboard":
        if len(args) < 1:
            raise ValueError("사용법: /vc onboard <startup_id> [today|7d]")
        startup_id = args[0].strip().lower()
        sample_period = args[1].strip().lower() if len(args) >= 2 else "today"
        return {
            "tool_name": "vc_onboarding_check",
            "tool_input": {"startup_id": startup_id, "sample_period": sample_period, "run_sample_collect": True},
        }

    if sub == "pending":
        startup_id = args[0].strip().lower() if args else ""
        payload: dict[str, Any] = {"action": "pending"}
        if startup_id:
            payload["startup_id"] = startup_id
        return {"tool_name": "vc_approval_queue", "tool_input": payload}

    if sub == "approve":
        if len(args) < 1:
            raise ValueError("사용법: /vc approve <approval_id>")
        force_high_risk = False
        approver = ""
        for token in args[1:]:
            raw = token.strip()
            low = raw.lower()
            if low in {"force", "--force", "high-risk-ok"}:
                force_high_risk = True
                continue
            if low.startswith("by="):
                approver = raw.split("=", 1)[1].strip()
                continue
            if not approver:
                approver = raw
        return {
            "tool_name": "vc_approval_queue",
            "tool_input": {
                "action": "approve",
                "approval_id": args[0].strip(),
                "force_high_risk": force_high_risk,
                "approver": approver,
            },
        }

    if sub == "reject":
        if len(args) < 1:
            raise ValueError("사용법: /vc reject <approval_id> [reason]")
        reason = " ".join(args[1:]).strip() if len(args) >= 2 else "manual reject"
        return {
            "tool_name": "vc_approval_queue",
            "tool_input": {"action": "reject", "approval_id": args[0].strip(), "reason": reason},
        }

    if sub == "status":
        if len(args) < 1:
            raise ValueError("사용법: /vc status <startup_id>")
        return {
            "tool_name": "vc_collect_bundle",
            "tool_input": {"action": "status", "startup_id": args[0].strip().lower()},
        }

    if sub == "scope":
        if len(args) < 1:
            raise ValueError("사용법: /vc scope <startup_id> [allow=<csv> deny=<csv> docs=<csv> consent=<ref> retention=<days>]")
        startup_id = args[0].strip().lower()
        if len(args) == 1 or args[1].strip().lower() in {"show", "get"}:
            return {"tool_name": "vc_scope_policy", "tool_input": {"action": "get", "startup_id": startup_id}}

        options = args[1:]
        if options and options[0].strip().lower() == "set":
            options = options[1:]
        payload: dict[str, Any] = {"action": "set", "startup_id": startup_id}
        for token in options:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            k = key.strip().lower()
            v = value.strip()
            if not v:
                continue
            if k in {"allow", "allow_prefixes"}:
                payload["allow_prefixes"] = v
            elif k in {"deny", "deny_patterns"}:
                payload["deny_patterns"] = v
            elif k in {"docs", "allowed_doc_types"}:
                payload["allowed_doc_types"] = v
            elif k in {"consent", "consent_reference"}:
                payload["consent_reference"] = v
            elif k in {"retention", "retention_days"}:
                try:
                    payload["retention_days"] = int(v)
                except ValueError:
                    raise ValueError("retention 값은 숫자여야 합니다.") from None
        return {"tool_name": "vc_scope_policy", "tool_input": payload}

    if sub == "scope-audit":
        if len(args) < 1:
            raise ValueError("사용법: /vc scope-audit <startup_id> [limit] [allow|reject]")
        startup_id = args[0].strip().lower()
        payload: dict[str, Any] = {"action": "audit", "startup_id": startup_id, "limit": 100}
        for token in args[1:]:
            raw = token.strip().lower()
            if raw in {"allow", "reject"}:
                payload["decision"] = raw
            else:
                try:
                    payload["limit"] = max(1, min(int(raw), 2000))
                except ValueError:
                    continue
        return {"tool_name": "vc_scope_policy", "tool_input": payload}

    if sub == "dashboard":
        startup_id = ""
        window = "30d"
        if args:
            first = args[0].strip().lower()
            if re.fullmatch(r"(?:\d+d|today|daily|weekly|week|month|30d|90d|7d)", first):
                window = first
            else:
                startup_id = first
        if len(args) >= 2:
            window = args[1].strip().lower() or "30d"
        payload: dict[str, Any] = {"window": window}
        if startup_id:
            payload["startup_id"] = startup_id
        return {"tool_name": "vc_ops_dashboard", "tool_input": payload}

    raise ValueError("지원하지 않는 /vc 명령입니다. /vc help 로 사용법을 확인하세요.")


def parse_integration_command(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    known_subcommands = set(INTEGRATION_PRIMARY_SUBCOMMANDS) | {"start", "시작", "도움말"}

    command_text = ""
    if lowered.startswith("/integration "):
        command_text = normalized[len("/integration ") :].strip()
    elif lowered == "/integration":
        return {"tool_name": "__integration_help__", "tool_input": {}}
    elif lowered.startswith("/int "):
        command_text = normalized[len("/int ") :].strip()
    elif lowered == "/int":
        return {"tool_name": "__integration_help__", "tool_input": {}}
    elif lowered.startswith("integration "):
        candidate = normalized[len("integration ") :].strip()
        head = candidate.split(maxsplit=1)[0].strip().lower() if candidate else ""
        if head in known_subcommands:
            command_text = candidate

    if not command_text:
        return None

    parts = command_text.split()
    sub = parts[0].strip().lower()
    args = parts[1:]

    if sub in {"help", "start", "시작", "도움말"}:
        return {"tool_name": "__integration_help__", "tool_input": {}}

    if sub == "connect":
        if len(args) < 2:
            raise ValueError(
                "사용법: /integration connect <startup_id> <google_drive|google_gmail|google> [client_id=<id>] [client_secret=<secret>] [scopes=<csv>]"
            )
        startup_id = args[0].strip().lower()
        provider = args[1].strip().lower()
        payload: dict[str, Any] = {"action": "connect", "startup_id": startup_id, "provider": provider}
        for token in args[2:]:
            raw = token.strip()
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            k = key.strip().lower()
            v = value.strip()
            if not v:
                continue
            if k in {"client_id", "clientid"}:
                payload["client_id"] = v
            elif k in {"client_secret", "clientsecret"}:
                payload["client_secret"] = v
            elif k in {"scopes", "scope"}:
                payload["scopes"] = v
            elif k in {"redirect_uri", "redirect"}:
                payload["redirect_uri"] = v
            elif k in {"mode"}:
                payload["mode"] = v
        return {"tool_name": "google_oauth_connect", "tool_input": payload}

    if sub == "exchange":
        if len(args) < 2:
            raise ValueError("사용법: /integration exchange <connection_id> code=<auth_code> [redirect_uri=<uri>]")
        connection_id = args[0].strip()
        payload: dict[str, Any] = {"action": "exchange_code", "connection_id": connection_id}
        for token in args[1:]:
            raw = token.strip()
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            k = key.strip().lower()
            v = value.strip()
            if not v:
                continue
            if k == "code":
                payload["code"] = v
            elif k in {"redirect_uri", "redirect"}:
                payload["redirect_uri"] = v
        if not str(payload.get("code", "")).strip():
            raise ValueError("사용법: /integration exchange <connection_id> code=<auth_code> [redirect_uri=<uri>]")
        return {"tool_name": "google_oauth_connect", "tool_input": payload}

    if sub == "refresh":
        if len(args) < 1:
            raise ValueError("사용법: /integration refresh <connection_id> [force] [min_valid_seconds=<n>]")
        payload: dict[str, Any] = {"action": "refresh_token", "connection_id": args[0].strip()}
        for token in args[1:]:
            raw = token.strip()
            low = raw.lower()
            if low in {"force", "--force"}:
                payload["force_refresh"] = True
                continue
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            k = key.strip().lower()
            v = value.strip()
            if not v:
                continue
            if k in {"min_valid_seconds", "min", "min_seconds"}:
                try:
                    payload["min_valid_seconds"] = int(v)
                except ValueError:
                    raise ValueError("min_valid_seconds 값은 숫자여야 합니다.") from None
            elif k in {"redirect_uri", "redirect"}:
                payload["redirect_uri"] = v
        return {"tool_name": "google_oauth_connect", "tool_input": payload}

    if sub == "test":
        if len(args) < 1:
            raise ValueError("사용법: /integration test <connection_id>")
        return {
            "tool_name": "google_oauth_connect",
            "tool_input": {"action": "test", "connection_id": args[0].strip()},
        }

    if sub == "status":
        if len(args) < 1:
            raise ValueError("사용법: /integration status <startup_id> [provider]")
        payload: dict[str, Any] = {"action": "status", "startup_id": args[0].strip().lower()}
        if len(args) >= 2 and args[1].strip():
            payload["provider"] = args[1].strip().lower()
        return {"tool_name": "google_oauth_connect", "tool_input": payload}

    if sub == "revoke":
        if len(args) < 1:
            raise ValueError("사용법: /integration revoke <connection_id> [reason]")
        reason = " ".join(args[1:]).strip() if len(args) >= 2 else "manual revoke"
        return {
            "tool_name": "google_oauth_connect",
            "tool_input": {"action": "revoke", "connection_id": args[0].strip(), "reason": reason},
        }

    raise ValueError("지원하지 않는 /integration 명령입니다. /integration help 로 사용법을 확인하세요.")


def parse_tool_only_mode_command(text: str) -> bool | None:
    normalized = text.strip().lower()
    if normalized in {"/tool-only on", "/toolonly on", "tool-only on", "tool only on", "도구만 on"}:
        return True
    if normalized in {"/tool-only off", "/toolonly off", "tool-only off", "tool only off", "도구만 off"}:
        return False
    if normalized in {
        "/tool-only",
        "/toolonly",
        "도구만 사용",
        "앞으로 도구만 사용해서 답해",
        "앞으로 도구만 사용해서 답하거라",
    }:
        return True
    if any(token in normalized for token in ("도구만 해제", "도구 전용 해제", "tool only off", "disable tool-only")):
        return False
    return None


def parse_set_permission_command(text: str) -> tuple[str, str] | None:
    normalized = text.strip()
    if not normalized.lower().startswith("/set-permission "):
        return None
    parts = normalized.split()
    if len(parts) != 3:
        raise ValueError("사용법: /set-permission <tool_name> <allow|prompt|deny>")
    tool_name = parts[1].strip()
    mode = parts[2].strip().lower()
    if not tool_name:
        raise ValueError("tool_name 값이 필요합니다.")
    if mode not in {"allow", "prompt", "deny"}:
        raise ValueError("권한 모드는 allow/prompt/deny 중 하나여야 합니다.")
    return tool_name, mode


def parse_memory_command(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized.lower().startswith("/memory"):
        return None
    parts = normalized.split(maxsplit=2)
    if len(parts) == 1:
        return {"action": "status"}
    action = parts[1].strip().lower()
    if action == "status":
        return {"action": "status"}
    if action == "latest":
        count = 5
        if len(parts) >= 3 and parts[2].strip():
            try:
                count = int(parts[2].strip())
            except ValueError as exc:
                raise ValueError("사용법: /memory latest <count> (count는 숫자)") from exc
        return {"action": "latest", "count": max(1, min(count, 50))}
    if action == "query":
        if len(parts) < 3 or not parts[2].strip():
            raise ValueError("사용법: /memory query <text>")
        return {"action": "query", "text": parts[2].strip()}
    raise ValueError("지원하지 않는 memory 명령입니다. (/memory status|latest|query)")


def parse_reflexion_command(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized.lower().startswith("/reflexion"):
        return None
    parts = normalized.split(maxsplit=2)
    if len(parts) == 1:
        return {"action": "status"}
    action = parts[1].strip().lower()
    if action == "status":
        return {"action": "status"}
    if action == "latest":
        count = 10
        if len(parts) >= 3 and parts[2].strip():
            try:
                count = int(parts[2].strip())
            except ValueError as exc:
                raise ValueError("사용법: /reflexion latest <count> (count는 숫자)") from exc
        return {"action": "latest", "count": max(1, min(count, 100))}
    if action == "query":
        if len(parts) < 3 or not parts[2].strip():
            raise ValueError("사용법: /reflexion query <text>")
        return {"action": "query", "text": parts[2].strip()}
    raise ValueError("지원하지 않는 reflexion 명령입니다. (/reflexion status|latest|query)")


def parse_feedback_command(text: str) -> str | None:
    normalized = text.strip()
    if not normalized.lower().startswith("/feedback"):
        return None
    payload = normalized[len("/feedback") :].strip()
    if not payload:
        raise ValueError("사용법: /feedback <피드백 내용>")
    return payload


def parse_delegate_command(text: str) -> str | None:
    normalized = text.strip()
    if not normalized.lower().startswith("/delegate"):
        return None
    payload = normalized[len("/delegate") :].strip()
    if not payload:
        raise ValueError("사용법: /delegate <요청>")
    return payload


def parse_schedule_arxiv_command(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized.lower().startswith("/schedule-arxiv"):
        return None
    parts = normalized.split(maxsplit=2)
    if len(parts) < 2:
        raise ValueError("사용법: /schedule-arxiv <HH:MM> [keywords...]")
    hhmm = parts[1].strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", hhmm):
        raise ValueError("시간 형식은 HH:MM 이어야 합니다. 예: /schedule-arxiv 08:00 deepseek llm")
    keywords: list[str] = []
    if len(parts) >= 3 and parts[2].strip():
        raw = parts[2].strip().replace(",", " ")
        for token in raw.split():
            t = token.strip()
            if t and t not in keywords:
                keywords.append(t)
    if not keywords:
        keywords = ["llm"]
    return {"time": hhmm, "keywords": keywords}


def parse_arxiv_quick_request(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    source_tokens = ("arxiv", "아카이브")
    topic_tokens = ("논문", "paper", "papers")
    action_tokens = (
        "요약",
        "찾",
        "검색",
        "가져",
        "정리",
        "보여",
        "불러",
        "다운로드",
        "알려",
        "list",
        "fetch",
        "search",
        "summar",
        "download",
    )
    if not any(token in lowered for token in action_tokens):
        return None
    if not any(token in lowered for token in source_tokens + topic_tokens):
        return None

    count_match = re.search(r"(\d+)\s*(개|편|papers?)", normalized, re.IGNORECASE)
    if count_match is None:
        count_match = re.search(r"\b(\d+)\b", normalized)
    max_papers = 3
    if count_match:
        try:
            max_papers = int(count_match.group(1))
        except ValueError:
            max_papers = 3
    max_papers = max(1, min(max_papers, 20))

    if "오늘" in normalized or "today" in lowered:
        days_back = 1
    elif "어제" in normalized or "yesterday" in lowered:
        days_back = 2
    elif any(token in lowered for token in ("예전", "과거", "옛", "이전", "지난", "old", "older", "historical")):
        days_back = 3650
    elif any(token in lowered for token in ("최근", "최신", "latest", "recent")):
        days_back = 14
    else:
        days_back = 365

    keywords: list[str] = []
    keyword_map = {
        "deepseek": "deepseek",
        "deep seek": "deepseek",
        "딥시크": "deepseek",
        "llm": "llm",
        "머신러닝": "machine learning",
        "machine learning": "machine learning",
        "강화학습": "reinforcement learning",
        "vision": "computer vision",
        "컴퓨터비전": "computer vision",
        "nlp": "nlp",
    }
    for trigger, mapped in keyword_map.items():
        if trigger in lowered and mapped not in keywords:
            keywords.append(mapped)

    quoted = re.findall(r"['\"]([^'\"]{2,80})['\"]", normalized)
    for phrase in quoted:
        term = phrase.strip()
        if term and term not in keywords:
            keywords.append(term)

    payload: dict[str, Any] = {
        "max_papers": max_papers,
        "days_back": days_back,
        "output": "text",
    }
    if keywords:
        payload["keywords"] = keywords
    return payload


def parse_deep_weekly_quick_request(text: str) -> dict[str, Any] | None:
    normalized = text.strip()
    if not normalized:
        return None

    lowered = normalized.lower()
    explicit_tokens = (
        "deep_weekly_retrospective",
        "deep weekly retrospective",
        "딥 위클리",
        "깊은 주간 회고",
        "깊이 있는 주간 회고",
    )
    retrospective_tokens = ("회고", "retrospective", "리트로")
    depth_tokens = ("깊", "deep", "상세", "디테일", "길게", "1만자", "롱폼")
    action_tokens = (
        "해줘",
        "작성",
        "만들",
        "생성",
        "정리",
        "요약",
        "출력",
        "보여",
        "돌려",
        "실행",
        "run",
        "generate",
    )

    has_explicit = any(token in lowered for token in explicit_tokens)
    has_retrospective = any(token in lowered for token in retrospective_tokens)
    has_depth = any(token in lowered for token in depth_tokens)
    has_action = any(token in lowered for token in action_tokens)
    if not has_explicit and not (has_retrospective and has_depth and has_action):
        return None

    days_back = 7
    days_match = re.search(r"(\d+)\s*(일|days?)", normalized, re.IGNORECASE)
    weeks_match = re.search(r"(\d+)\s*(주|weeks?)", normalized, re.IGNORECASE)
    if days_match:
        try:
            days_back = int(days_match.group(1))
        except ValueError:
            days_back = 7
    elif weeks_match:
        try:
            days_back = int(weeks_match.group(1)) * 7
        except ValueError:
            days_back = 7
    elif "지난주" in normalized or "이번 주" in normalized or "이번주" in normalized:
        days_back = 7

    return {"days_back": max(1, min(days_back, 90))}


def summarize_for_memory(text: str, max_chars: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


def _bool_env_local(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _float_env_local(name: str, default: float = 0.0) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _try_parse_json(text: str) -> Any | None:
    body = text.strip()
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def format_user_output(text: str) -> str:
    parsed = _try_parse_json(text)
    if parsed is None:
        return text

    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"오류: {error}"

        summary = parsed.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary

        nested_result = parsed.get("result")
        if isinstance(nested_result, str) and nested_result.strip():
            nested = _try_parse_json(nested_result)
            if isinstance(nested, dict):
                nested_error = nested.get("error")
                if isinstance(nested_error, str) and nested_error.strip():
                    return f"오류: {nested_error}"
                nested_summary = nested.get("summary")
                if isinstance(nested_summary, str) and nested_summary.strip():
                    return nested_summary
                return json.dumps(nested, ensure_ascii=False, indent=2)
            return nested_result

        return json.dumps(parsed, ensure_ascii=False, indent=2)

    if isinstance(parsed, list):
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    return str(parsed)


def format_permissions_map(permissions: dict[str, str]) -> str:
    if not permissions:
        return "현재 명시된 도구 권한이 없습니다. (기본값: allow)"
    lines = ["현재 도구 권한 정책:"]
    for name in sorted(permissions.keys()):
        lines.append(f"- {name}: {permissions[name]}")
    lines.append("변경 예시: /set-permission run_shell deny")
    return "\n".join(lines)


def format_memory_query_result(query: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return f"메모리 검색 결과가 없습니다: {query}"
    lines = [f"메모리 검색 결과 ({len(items)}건): {query}"]
    for idx, item in enumerate(items, start=1):
        score = float(item.get("score", 0.0) or 0.0)
        role = str(item.get("role", ""))
        ts = str(item.get("ts", ""))
        summary = str(item.get("summary", ""))
        lines.append(f"{idx}. [{role}] score={score:.3f} ts={ts}")
        lines.append(f"   {summary}")
    return "\n".join(lines)


def format_reflexion_records(items: list[dict[str, Any]]) -> str:
    if not items:
        return "리플렉션 기록이 없습니다."
    lines = [f"리플렉션 최근 기록 ({len(items)}건):"]
    for idx, item in enumerate(items, start=1):
        row_type = str(item.get("type", ""))
        kind = str(item.get("kind", ""))
        ts = str(item.get("ts", ""))
        source = str(item.get("source", ""))
        text = str(item.get("text", item.get("outcome", ""))).strip()
        if len(text) > 140:
            text = text[:137] + "..."
        label = f"{row_type}/{kind}" if kind else row_type
        lines.append(f"{idx}. [{label}] ts={ts} source={source}")
        if text:
            lines.append(f"   {text}")
    return "\n".join(lines)


def parse_context_command(text: str) -> dict[str, Any] | None:
    """
    /context [minutes] 명령어 파싱

    예시:
    - /context
    - /context 60
    """
    normalized = text.strip()
    if not normalized.lower().startswith("/context"):
        return None

    payload = normalized[len("/context"):].strip()

    result = {}
    if payload and payload.isdigit():
        result["lookback_minutes"] = int(payload)

    return result


def parse_today_command(text: str) -> dict[str, Any] | None:
    """
    /today [keyword] 명령어 파싱

    예시:
    - /today
    - /today BoramClaw
    """
    normalized = text.strip()
    if not normalized.lower().startswith("/today"):
        return None

    payload = normalized[len("/today"):].strip()

    result = {"mode": "daily"}
    if payload:
        result["focus_keyword"] = payload

    return result


def parse_week_command(text: str) -> dict[str, Any] | None:
    """
    /week [keyword] 명령어 파싱

    예시:
    - /week
    - /week Claude
    """
    normalized = text.strip()
    if not normalized.lower().startswith("/week"):
        return None

    payload = normalized[len("/week"):].strip()

    result = {"mode": "weekly"}
    if payload:
        result["focus_keyword"] = payload

    return result


def format_workday_recap(report_data: dict[str, Any]) -> str:
    """
    workday_recap 툴의 결과를 사용자 친화적으로 포맷팅

    Args:
        report_data: workday_recap의 run() 결과

    Returns:
        포맷된 문자열
    """
    if report_data.get("status") != "success":
        error = report_data.get("message", "알 수 없는 오류")
        return f"❌ 리포트 생성 실패: {error}"

    report = report_data.get("report", {})
    mode = report.get("mode", "daily")
    period_label = "오늘" if mode == "daily" else "이번 주"
    summary = report.get("summary", "")
    sections = report.get("sections", {})
    errors = report.get("errors", [])

    lines = [
        f"📊 {period_label} 개발 활동 리포트",
        f"생성 시간: {report.get('generated_at', 'N/A')}",
        "",
        f"✨ {summary}",
        "",
    ]

    # Git 섹션
    if "git" in sections:
        git = sections["git"]
        commits = git.get("total_commits", 0)
        if commits > 0:
            lines.append("### 📝 Git 활동")
            lines.append(f"- 커밋: {commits}개")
            lines.append(f"- 변경: +{git.get('insertions', 0)} -{git.get('deletions', 0)} (파일 {git.get('files_changed', 0)}개)")

            authors = git.get("authors", [])
            if authors:
                author_names = ", ".join(authors[:3])
                lines.append(f"- 작성자: {author_names}")

            branches = git.get("active_branches", [])
            if branches:
                branch_names = ", ".join(branches[:3])
                lines.append(f"- 활성 브랜치: {branch_names}")
            lines.append("")

    # Shell 섹션
    if "shell" in sections:
        shell = sections["shell"]
        total_cmds = shell.get("total_commands", 0)
        if total_cmds > 0:
            lines.append("### 💻 Shell 활동")
            lines.append(f"- 명령어 실행: {total_cmds}개 (유니크: {shell.get('unique_commands', 0)}개)")

            top_commands = shell.get("top_commands", [])
            if top_commands:
                lines.append("- 자주 쓴 명령어:")
                for cmd_info in top_commands[:5]:
                    if isinstance(cmd_info, dict):
                        cmd = cmd_info.get("command", "")
                        count = cmd_info.get("count", 0)
                        lines.append(f"  • {cmd}: {count}회")

            alias_suggestions = shell.get("alias_suggestions", [])
            if alias_suggestions:
                lines.append("- Alias 추천:")
                for suggestion in alias_suggestions[:3]:
                    if isinstance(suggestion, dict):
                        cmd = suggestion.get("command", "")
                        count = suggestion.get("count", 0)
                        lines.append(f"  • {cmd} ({count}회)")
            lines.append("")

    # Browser 섹션
    if "browser" in sections:
        browser = sections["browser"]
        visits = browser.get("total_visits", 0)
        if visits > 0:
            lines.append("### 🌐 Browser 활동")
            lines.append(f"- 방문: {visits}개 페이지 (도메인 {browser.get('unique_domains', 0)}개)")
            lines.append(f"- 세션: {browser.get('sessions', 0)}개")

            top_domains = browser.get("top_domains", [])
            if top_domains:
                lines.append("- 자주 방문한 도메인:")
                for domain_info in top_domains[:5]:
                    if isinstance(domain_info, dict):
                        domain = domain_info.get("domain", "")
                        count = domain_info.get("count", 0)
                        lines.append(f"  • {domain}: {count}회")
            lines.append("")

    # Screen 섹션
    if "screen" in sections:
        screen = sections["screen"]
        captures = screen.get("total_captures", 0)
        if captures > 0:
            lines.append("### 🖥️  Screen 활동 (screenpipe)")
            lines.append(f"- 캡처: {captures}개")

            focus_keyword = screen.get("focus_keyword")
            if focus_keyword:
                lines.append(f"- 검색 키워드: '{focus_keyword}'")

            top_apps = screen.get("top_apps", [])
            if top_apps:
                lines.append("- 자주 사용한 앱:")
                for app_name, count in top_apps[:5]:
                    lines.append(f"  • {app_name}: {count}회")
            lines.append("")

    # 에러 섹션
    if errors:
        lines.append("### ⚠️  경고")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)
