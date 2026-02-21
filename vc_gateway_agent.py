#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import time
from typing import Any
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from vc_platform.classifier import classify_document


def _iso_to_dt(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class GatewayConfig:
    startup_id: str
    folders: dict[str, Path]
    shared_secret: str
    max_artifacts: int


def load_gateway_config(config_path: Path) -> GatewayConfig:
    parsed = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("gateway config must be a JSON object")
    startup_id = str(parsed.get("startup_id", "")).strip().lower()
    if not startup_id:
        raise ValueError("gateway config requires startup_id")
    folders_raw = parsed.get("folders", {})
    if not isinstance(folders_raw, dict) or not folders_raw:
        raise ValueError("gateway config requires folders mapping")
    folders: dict[str, Path] = {}
    for alias, root in folders_raw.items():
        alias_name = str(alias).strip()
        root_str = str(root).strip()
        if not alias_name or not root_str:
            continue
        resolved = Path(root_str).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"folder does not exist: {alias_name} -> {resolved}")
        folders[alias_name] = resolved
    if not folders:
        raise ValueError("gateway config folders are empty")
    shared_secret = str(parsed.get("shared_secret", "")).strip()
    max_artifacts = int(parsed.get("max_artifacts", 500) or 500)
    return GatewayConfig(
        startup_id=startup_id,
        folders=folders,
        shared_secret=shared_secret,
        max_artifacts=max(1, min(max_artifacts, 5000)),
    )


class GatewayState:
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config

    def _verify_signature(self, *, body: bytes, headers: dict[str, str]) -> tuple[bool, str]:
        if not self.config.shared_secret:
            return True, "signature disabled"
        ts = headers.get("x-vc-timestamp", "").strip()
        sig = headers.get("x-vc-signature", "").strip()
        if not ts or not sig:
            return False, "missing signature headers"
        try:
            ts_int = int(ts)
        except ValueError:
            return False, "invalid timestamp header"
        if abs(int(time.time()) - ts_int) > 300:
            return False, "timestamp out of range"
        message = ts.encode("utf-8") + b"." + body
        expected = hmac.new(self.config.shared_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return False, "invalid signature"
        return True, "ok"

    def _resolve_rel_path(self, rel_path: str) -> Path:
        normalized = rel_path.strip().replace("\\", "/")
        if not normalized or normalized.startswith("/"):
            raise ValueError("invalid rel_path")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) < 2:
            raise ValueError("rel_path must be <alias>/<relative_path>")
        alias = parts[0]
        if alias not in self.config.folders:
            raise ValueError(f"unknown alias: {alias}")
        root = self.config.folders[alias]
        rel_parts = parts[1:]
        if any(part == ".." for part in rel_parts):
            raise ValueError("path traversal is not allowed")
        candidate = root / Path(*rel_parts)
        if candidate.is_symlink():
            raise PermissionError("symlink access is not allowed")
        target = candidate.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("path escaped alias root") from exc
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"file not found: {rel_path}")
        return target

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "startup_id": self.config.startup_id,
            "folders": sorted(list(self.config.folders.keys())),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def manifest(self, payload: dict[str, Any]) -> dict[str, Any]:
        startup_id = str(payload.get("startup_id", "")).strip().lower()
        if startup_id != self.config.startup_id:
            raise PermissionError("startup_id mismatch")
        request_id = str(payload.get("request_id", "")).strip()
        if not request_id:
            raise ValueError("request_id is required")

        doc_types_raw = payload.get("doc_types", [])
        doc_types = set()
        if isinstance(doc_types_raw, list):
            doc_types = {str(item).strip() for item in doc_types_raw if str(item).strip()}
        include_ocr = bool(payload.get("include_ocr", False))
        folder_alias = str(payload.get("folder_alias", "")).strip()
        max_artifacts = int(payload.get("max_artifacts", self.config.max_artifacts) or self.config.max_artifacts)
        max_artifacts = max(1, min(max_artifacts, self.config.max_artifacts))

        window_from = _iso_to_dt(str(payload.get("window_from", "")))
        window_to = _iso_to_dt(str(payload.get("window_to", "")))

        aliases = [folder_alias] if folder_alias else sorted(self.config.folders.keys())
        artifacts: list[dict[str, Any]] = []
        for alias in aliases:
            root = self.config.folders.get(alias)
            if root is None:
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.is_symlink():
                    continue
                resolved = path.resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    continue
                stat = resolved.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if window_from and mtime < window_from:
                    continue
                if window_to and mtime > window_to:
                    continue
                doc_type, confidence = classify_document(resolved, include_ocr=include_ocr)
                if doc_types and doc_type not in doc_types:
                    continue
                raw = resolved.read_bytes()
                digest = _sha256_bytes(raw)
                rel = resolved.relative_to(root).as_posix()
                rel_path = f"{alias}/{rel}"
                artifacts.append(
                    {
                        "artifact_id": f"sha256:{digest}",
                        "rel_path": rel_path,
                        "size_bytes": stat.st_size,
                        "mtime": mtime.isoformat(),
                        "sha256": digest,
                        "doc_type": doc_type,
                        "confidence": confidence,
                    }
                )

        artifacts.sort(key=lambda item: str(item.get("mtime", "")), reverse=True)
        return {"ok": True, "request_id": request_id, "artifacts": artifacts[:max_artifacts]}

    def artifact_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        startup_id = str(payload.get("startup_id", "")).strip().lower()
        if startup_id != self.config.startup_id:
            raise PermissionError("startup_id mismatch")
        rel_path = str(payload.get("rel_path", "")).strip()
        if not rel_path:
            raise ValueError("rel_path is required")
        target = self._resolve_rel_path(rel_path)
        raw = target.read_bytes()
        digest = _sha256_bytes(raw)
        return {
            "ok": True,
            "artifact": {
                "rel_path": rel_path,
                "size_bytes": len(raw),
                "sha256": digest,
                "content_b64": base64.b64encode(raw).decode("ascii"),
            },
        }


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "OpenClawGateway/0.1"

    @property
    def state(self) -> GatewayState:
        return self.server.state  # type: ignore[attr-defined]

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        raw_len = self.headers.get("Content-Length", "0")
        try:
            size = int(raw_len)
        except ValueError:
            size = 0
        size = max(0, min(size, 20 * 1024 * 1024))
        return self.rfile.read(size)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json_response(404, {"ok": False, "error": "not found"})
            return
        self._json_response(200, self.state.health())

    def do_POST(self) -> None:  # noqa: N802
        body = self._read_body()
        ok, reason = self.state._verify_signature(
            body=body,
            headers={k.lower(): v for k, v in self.headers.items()},
        )
        if not ok:
            self._json_response(401, {"ok": False, "error": reason})
            return

        try:
            parsed = json.loads(body.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("JSON body must be object")
        except Exception as exc:
            self._json_response(400, {"ok": False, "error": f"invalid json: {exc}"})
            return

        try:
            if self.path == "/manifest":
                payload = self.state.manifest(parsed)
                self._json_response(200, payload)
                return
            if self.path == "/artifact-content":
                payload = self.state.artifact_content(parsed)
                self._json_response(200, payload)
                return
            self._json_response(404, {"ok": False, "error": "not found"})
        except PermissionError as exc:
            self._json_response(403, {"ok": False, "error": str(exc)})
        except FileNotFoundError as exc:
            self._json_response(404, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json_response(400, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw VC gateway agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8742)
    parser.add_argument("--config", default="config/vc_gateway.json")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        raise SystemExit(f"gateway config not found: {config_path}")
    config = load_gateway_config(config_path)

    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    server.state = GatewayState(config)  # type: ignore[attr-defined]
    print(f"VC gateway started on http://{args.host}:{args.port} for startup_id={config.startup_id}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
