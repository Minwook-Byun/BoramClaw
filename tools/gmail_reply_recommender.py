from __future__ import annotations

import argparse
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.policy import default as email_policy
import imaplib
import json
import os
import sys
import time
from typing import Any


__version__ = "1.2.0"

TOOL_SPEC = {
    "name": "gmail_reply_recommender",
    "description": "Read Gmail messages and generate simple reply recommendations. Optionally create drafts or send replies.",
    "version": "1.2.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail query, e.g. is:unread newer_than:1d"},
            "max_messages": {"type": "integer", "minimum": 1, "maximum": 50},
            "create_drafts": {"type": "boolean"},
            "send_messages": {"type": "boolean"},
            "mark_as_read": {"type": "boolean"},
            "use_imap_fallback": {"type": "boolean", "description": "Fallback to IMAP when Gmail API fails"},
        },
    },
}


def _extract_http_status(exc: Exception) -> int | None:
    resp = getattr(exc, "resp", None)
    if resp is None:
        return None
    status = getattr(resp, "status", None)
    if isinstance(status, int):
        return status
    return None


def _run_with_retry(callable_api: Any, max_retries: int = 3, initial_backoff: int = 1) -> Any:
    backoff = max(1, int(initial_backoff))
    for attempt in range(max_retries):
        try:
            return callable_api()
        except Exception as exc:
            status = _extract_http_status(exc)
            if status == 429 and attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            if status == 401:
                raise RuntimeError("Gmail authentication failed. Please re-authenticate.") from exc
            if status == 429:
                raise RuntimeError("Gmail API quota exceeded. Retrying failed after multiple attempts.") from exc
            raise
    raise RuntimeError("Gmail API retry loop exhausted unexpectedly.")


def _load_credentials() -> Any:
    # Lazy import to keep this tool optional.
    from google.oauth2.credentials import Credentials  # type: ignore

    token_json = os.getenv("GMAIL_OAUTH_TOKEN_JSON", "").strip()
    token_file = os.getenv("GMAIL_OAUTH_TOKEN_FILE", "").strip()

    if token_json:
        data = json.loads(token_json)
        return Credentials.from_authorized_user_info(data)
    if token_file:
        with open(token_file, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return Credentials.from_authorized_user_info(data)
    raise ValueError("Set GMAIL_OAUTH_TOKEN_JSON or GMAIL_OAUTH_TOKEN_FILE.")


def _build_gmail() -> Any:
    from googleapiclient.discovery import build  # type: ignore

    creds = _load_credentials()
    return build("gmail", "v1", credentials=creds)


def _extract_headers(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in payload.get("headers", []) or []:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name", "")).lower()
        value = str(header.get("value", ""))
        if name:
            result[name] = value
    return result


def _recommend_reply(subject: str, sender: str, snippet: str) -> str:
    return (
        f"안녕하세요 {sender}님,\n\n"
        f"메일 제목 '{subject}' 확인했습니다. 아래 내용 기반으로 검토 후 답변드리겠습니다.\n"
        f"- 요약: {snippet[:160]}\n\n"
        "감사합니다."
    )


def _decode_mime(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _imap_search_criteria(query: str) -> tuple[str, ...]:
    q = query.lower().strip()
    if not q:
        return ("UNSEEN",)
    if "is:unread" in q:
        return ("UNSEEN",)
    return ("ALL",)


def _run_imap_fallback(query: str, max_messages: int, mark_as_read: bool = False) -> list[dict[str, Any]]:
    host = (os.getenv("GMAIL_IMAP_HOST") or "imap.gmail.com").strip()
    port = int(os.getenv("GMAIL_IMAP_PORT") or "993")
    username = (os.getenv("GMAIL_IMAP_USER") or "").strip()
    password = (os.getenv("GMAIL_IMAP_APP_PASSWORD") or "").strip()
    if not username or not password:
        raise RuntimeError("IMAP fallback requires GMAIL_IMAP_USER and GMAIL_IMAP_APP_PASSWORD")

    criteria = _imap_search_criteria(query)
    outputs: list[dict[str, Any]] = []
    with imaplib.IMAP4_SSL(host, port) as client:
        client.login(username, password)
        typ, _ = client.select("INBOX")
        if typ != "OK":
            raise RuntimeError("IMAP INBOX select failed")
        typ, data = client.search(None, *criteria)
        if typ != "OK":
            raise RuntimeError("IMAP search failed")
        message_ids = []
        if data and isinstance(data[0], (bytes, bytearray)):
            message_ids = [x for x in data[0].split() if x]
        # newest first
        for msg_id in list(reversed(message_ids))[: max_messages]:
            typ, msg_data = client.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            if typ != "OK" or not msg_data:
                continue
            header_bytes = b""
            for part in msg_data:
                if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                    header_bytes = bytes(part[1])
                    break
            if not header_bytes:
                continue
            message = BytesParser(policy=email_policy).parsebytes(header_bytes)
            subject = _decode_mime(str(message.get("Subject", "(no subject)")))
            sender = _decode_mime(str(message.get("From", "(unknown sender)")))
            date = str(message.get("Date", ""))
            snippet = f"IMAP header date={date}".strip()
            recommendation = _recommend_reply(subject=subject, sender=sender, snippet=snippet)
            item: dict[str, Any] = {
                "id": msg_id.decode("utf-8", errors="ignore"),
                "thread_id": "",
                "subject": subject,
                "from": sender,
                "snippet": snippet,
                "recommended_reply": recommendation,
                "source": "imap_fallback",
            }
            outputs.append(item)
            if mark_as_read:
                client.store(msg_id, "+FLAGS", "\\Seen")
    return outputs


def _run_gmail_api(
    gmail: Any,
    *,
    query: str,
    max_messages: int,
    create_drafts: bool,
    send_messages: bool,
    mark_as_read: bool,
) -> list[dict[str, Any]]:
    listed = _run_with_retry(
        lambda: gmail.users().messages().list(userId="me", q=query, maxResults=max_messages).execute()
    )
    message_refs = listed.get("messages", []) or []

    outputs: list[dict[str, Any]] = []
    for ref in message_refs:
        msg_id = str(ref.get("id", ""))
        if not msg_id:
            continue

        msg = _run_with_retry(
            lambda: gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()
        )
        payload = msg.get("payload", {}) or {}
        headers = _extract_headers(payload)
        subject = headers.get("subject", "(no subject)")
        sender = headers.get("from", "(unknown sender)")
        snippet = str(msg.get("snippet", ""))
        thread_id = str(msg.get("threadId", ""))
        recommendation = _recommend_reply(subject=subject, sender=sender, snippet=snippet)

        item: dict[str, Any] = {
            "id": msg_id,
            "thread_id": thread_id,
            "subject": subject,
            "from": sender,
            "snippet": snippet,
            "recommended_reply": recommendation,
            "source": "gmail_api",
        }

        if create_drafts or send_messages:
            import base64
            from email.mime.text import MIMEText

            message = MIMEText(recommendation, _charset="utf-8")
            message["to"] = sender
            message["subject"] = f"Re: {subject}"
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            if create_drafts:
                draft = _run_with_retry(
                    lambda: gmail.users()
                    .drafts()
                    .create(userId="me", body={"message": {"threadId": thread_id, "raw": raw}})
                    .execute()
                )
                item["draft_id"] = str(draft.get("id", ""))

            if send_messages:
                sent = _run_with_retry(
                    lambda: gmail.users()
                    .messages()
                    .send(userId="me", body={"threadId": thread_id, "raw": raw})
                    .execute()
                )
                item["sent_message_id"] = str(sent.get("id", ""))

        if mark_as_read:
            _run_with_retry(
                lambda: gmail.users()
                .messages()
                .modify(userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]})
                .execute()
            )
            item["marked_as_read"] = True

        outputs.append(item)
    return outputs


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    query = str(input_data.get("query", "is:unread newer_than:1d"))
    max_messages = int(input_data.get("max_messages", 10))
    create_drafts = bool(input_data.get("create_drafts", False))
    send_messages = bool(input_data.get("send_messages", False))
    mark_as_read = bool(input_data.get("mark_as_read", False))
    use_imap_fallback = bool(input_data.get("use_imap_fallback", True))

    try:
        gmail = _build_gmail()
        outputs = _run_gmail_api(
            gmail,
            query=query,
            max_messages=max_messages,
            create_drafts=create_drafts,
            send_messages=send_messages,
            mark_as_read=mark_as_read,
        )
        return {
            "ok": True,
            "query": query,
            "count": len(outputs),
            "results": outputs,
            "source": "gmail_api",
            "workdir": context.get("workdir", ""),
        }
    except Exception as exc:
        if use_imap_fallback:
            try:
                outputs = _run_imap_fallback(query=query, max_messages=max_messages, mark_as_read=mark_as_read)
                return {
                    "ok": True,
                    "query": query,
                    "count": len(outputs),
                    "results": outputs,
                    "source": "imap_fallback",
                    "warning": f"Gmail API failed, fallback used: {exc}",
                    "workdir": context.get("workdir", ""),
                }
            except Exception as fallback_exc:
                return {
                    "ok": False,
                    "error": str(exc),
                    "fallback_error": str(fallback_exc),
                    "hint": "Install Gmail API deps or configure IMAP fallback env vars.",
                }
        return {
            "ok": False,
            "error": str(exc),
            "hint": "Enable use_imap_fallback or configure Gmail API credentials.",
        }


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="gmail_reply_recommender cli")
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
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
