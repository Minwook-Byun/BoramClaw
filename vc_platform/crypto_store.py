from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:  # pragma: no cover - 의존성 미설치 환경 방어
    AESGCM = None  # type: ignore[assignment]


class VCCryptoStore:
    def __init__(self, key_file: str | Path) -> None:
        self.key_file = Path(key_file).resolve()
        self.key_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_doc(self) -> dict[str, Any]:
        if not self.key_file.exists():
            return {"keys": {}}
        try:
            parsed = json.loads(self.key_file.read_text(encoding="utf-8"))
        except Exception:
            return {"keys": {}}
        if not isinstance(parsed, dict):
            return {"keys": {}}
        keys = parsed.get("keys")
        if not isinstance(keys, dict):
            parsed["keys"] = {}
        return parsed

    def _save_doc(self, doc: dict[str, Any]) -> None:
        self.key_file.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _encode(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def _decode(text: str) -> bytes:
        return base64.b64decode(text.encode("ascii"))

    def _ensure_key(self, startup_id: str) -> tuple[bytes, int]:
        doc = self._load_doc()
        keys = doc.setdefault("keys", {})
        current = keys.get(startup_id)
        if not isinstance(current, dict):
            key_bytes = os.urandom(32)
            current = {
                "wrapped_key": self._encode(key_bytes),
                "version": 1,
                "created_at": self._now_iso(),
            }
            keys[startup_id] = current
            self._save_doc(doc)

        key_raw = current.get("wrapped_key", "")
        if not isinstance(key_raw, str) or not key_raw:
            raise RuntimeError(f"invalid key entry for startup_id={startup_id}")
        version_raw = current.get("version", 1)
        try:
            version = int(version_raw)
        except (TypeError, ValueError):
            version = 1
        return self._decode(key_raw), version

    def rotate_key(self, startup_id: str) -> dict[str, Any]:
        doc = self._load_doc()
        keys = doc.setdefault("keys", {})
        current = keys.get(startup_id)
        current_version = 0
        if isinstance(current, dict):
            try:
                current_version = int(current.get("version", 0))
            except (TypeError, ValueError):
                current_version = 0

        next_version = max(1, current_version + 1)
        keys[startup_id] = {
            "wrapped_key": self._encode(os.urandom(32)),
            "version": next_version,
            "created_at": self._now_iso(),
        }
        self._save_doc(doc)
        return {"startup_id": startup_id, "version": next_version}

    def encrypt_for_startup(self, startup_id: str, plaintext: bytes, *, aad: bytes | None = None) -> dict[str, Any]:
        if AESGCM is None:
            raise RuntimeError("cryptography dependency is required for AES-256-GCM encryption.")
        key, version = self._ensure_key(startup_id)
        aes = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aes.encrypt(nonce, plaintext, aad)
        return {
            "alg": "AES-256-GCM",
            "key_version": version,
            "nonce_b64": self._encode(nonce),
            "ciphertext_b64": self._encode(ciphertext),
            "created_at": self._now_iso(),
        }

    def decrypt_for_startup(self, startup_id: str, envelope: dict[str, Any], *, aad: bytes | None = None) -> bytes:
        if AESGCM is None:
            raise RuntimeError("cryptography dependency is required for AES-256-GCM decryption.")
        key, _ = self._ensure_key(startup_id)
        nonce_raw = str(envelope.get("nonce_b64", ""))
        ciphertext_raw = str(envelope.get("ciphertext_b64", ""))
        if not nonce_raw or not ciphertext_raw:
            raise ValueError("invalid envelope: nonce_b64/ciphertext_b64 required")
        nonce = self._decode(nonce_raw)
        ciphertext = self._decode(ciphertext_raw)
        aes = AESGCM(key)
        return aes.decrypt(nonce, ciphertext, aad)

