from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize(text: str, max_chars: int = 260) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[0-9A-Za-z가-힣_]+", text.lower())
    return {tok for tok in tokens if len(tok) >= 2}


def _stable_vector(text: str, dim: int) -> list[float]:
    if dim <= 0:
        return []
    vec = [0.0] * dim
    tokens = _tokenize(text)
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], byteorder="big", signed=False) % dim
        sign = 1.0 if (digest[4] & 0x1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


class _SQLiteVectorIndex:
    def __init__(self, db_path: Path, dim: int = 128) -> None:
        self.db_path = db_path
        self.dim = max(16, int(dim))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY,
                    ts TEXT,
                    session_id TEXT,
                    turn INTEGER,
                    role TEXT,
                    summary TEXT,
                    vector_json TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def upsert(self, record: dict[str, Any]) -> None:
        record_id = str(record.get("id", "")).strip()
        if not record_id:
            return
        summary = str(record.get("summary", ""))
        vec = _stable_vector(summary, self.dim)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO vectors(id, ts, session_id, turn, role, summary, vector_json)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    ts=excluded.ts,
                    session_id=excluded.session_id,
                    turn=excluded.turn,
                    role=excluded.role,
                    summary=excluded.summary,
                    vector_json=excluded.vector_json
                """,
                (
                    record_id,
                    str(record.get("ts", "")),
                    str(record.get("session_id", "")),
                    int(record.get("turn", 0) or 0),
                    str(record.get("role", "")),
                    summary,
                    json.dumps(vec, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def replace_all(self, records: list[dict[str, Any]]) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM vectors")
            for item in records:
                record_id = str(item.get("id", "")).strip()
                if not record_id:
                    continue
                summary = str(item.get("summary", ""))
                vec = _stable_vector(summary, self.dim)
                conn.execute(
                    """
                    INSERT INTO vectors(id, ts, session_id, turn, role, summary, vector_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        str(item.get("ts", "")),
                        str(item.get("session_id", "")),
                        int(item.get("turn", 0) or 0),
                        str(item.get("role", "")),
                        summary,
                        json.dumps(vec, ensure_ascii=False),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def query(self, text: str, top_k: int = 5) -> list[dict[str, Any]]:
        q = _stable_vector(text, self.dim)
        if not any(abs(v) > 1e-12 for v in q):
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, ts, session_id, turn, role, summary, vector_json FROM vectors"
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            try:
                vec = json.loads(str(row[6] or "[]"))
            except json.JSONDecodeError:
                continue
            if not isinstance(vec, list):
                continue
            v = [float(x) for x in vec]
            score = _cosine(q, v)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    {
                        "id": str(row[0]),
                        "ts": str(row[1] or ""),
                        "session_id": str(row[2] or ""),
                        "turn": int(row[3] or 0),
                        "role": str(row[4] or ""),
                        "summary": str(row[5] or ""),
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        out: list[dict[str, Any]] = []
        limit = max(1, min(int(top_k), 50))
        for score, payload in scored[:limit]:
            out.append({"score": round(float(score), 4), **payload})
        return out

    def count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
        finally:
            conn.close()
        if not row:
            return 0
        return int(row[0] or 0)


@dataclass
class MemoryHit:
    score: float
    ts: str
    session_id: str
    turn: int
    role: str
    summary: str
    record_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "id": self.record_id,
            "ts": self.ts,
            "session_id": self.session_id,
            "turn": self.turn,
            "role": self.role,
            "summary": self.summary,
        }


class LongTermMemoryStore:
    def __init__(
        self,
        workdir: str,
        file_path: str = "logs/long_term_memory.jsonl",
        max_records: int = 20000,
        vector_backend: str | None = None,
        vector_db_path: str | None = None,
        vector_dim: int = 128,
    ) -> None:
        self.workdir = Path(workdir).resolve()
        target = Path(file_path)
        if not target.is_absolute():
            target = (self.workdir / target).resolve()
        self.path = target
        self.max_records = max(100, int(max_records))
        self.path.parent.mkdir(parents=True, exist_ok=True)

        backend = (vector_backend or os.getenv("LONG_TERM_MEMORY_VECTOR_BACKEND") or "sqlite").strip().lower()
        self.vector_backend = backend
        self.vector_dim = max(16, int(vector_dim))
        self._vector_index: _SQLiteVectorIndex | None = None
        self._vector_status = "disabled"
        if backend == "sqlite":
            raw_db_path = vector_db_path or os.getenv("LONG_TERM_MEMORY_VECTOR_DB_FILE") or "logs/long_term_memory_vectors.sqlite"
            db_path = Path(raw_db_path)
            if not db_path.is_absolute():
                db_path = (self.workdir / db_path).resolve()
            try:
                self._vector_index = _SQLiteVectorIndex(db_path=db_path, dim=self.vector_dim)
                self._vector_status = "sqlite"
            except Exception:
                self._vector_index = None
                self._vector_status = "disabled:error"
        else:
            self._vector_status = "disabled"

        self._records: list[dict[str, Any]] = []
        self._load()

    def _normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        out = dict(record)
        rid = str(out.get("id", "")).strip()
        if not rid:
            rid = f"mem_{uuid4().hex[:16]}"
            out["id"] = rid
        out["ts"] = str(out.get("ts", ""))
        out["session_id"] = str(out.get("session_id", ""))
        out["turn"] = int(out.get("turn", 0) or 0)
        out["role"] = str(out.get("role", ""))
        out["summary"] = str(out.get("summary", ""))
        return out

    def _load(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        loaded: list[dict[str, Any]] = []
        changed = False
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            body = line.strip()
            if not body:
                continue
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                normalized = self._normalize_record(parsed)
                if normalized.get("id") != parsed.get("id"):
                    changed = True
                loaded.append(normalized)
        if len(loaded) > self.max_records:
            loaded = loaded[-self.max_records :]
            changed = True
        self._records = loaded
        if changed:
            self._rewrite_all_records()
        if self._vector_index is not None:
            self._vector_index.replace_all(self._records)

    def _rewrite_all_records(self) -> None:
        if not self._records:
            self.path.write_text("", encoding="utf-8")
            return
        self.path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in self._records) + "\n",
            encoding="utf-8",
        )

    def add(self, session_id: str, turn: int, role: str, text: str) -> None:
        summary = _summarize(text)
        if not summary:
            return
        record = {
            "id": f"mem_{uuid4().hex[:16]}",
            "ts": _utc_now(),
            "session_id": str(session_id),
            "turn": int(turn),
            "role": str(role),
            "summary": summary,
        }
        self._records.append(record)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]
            self._rewrite_all_records()
        else:
            with self.path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self._vector_index is not None:
            self._vector_index.upsert(record)

    def status(self) -> dict[str, Any]:
        vector_count = self._vector_index.count() if self._vector_index is not None else 0
        return {
            "path": str(self.path),
            "records": len(self._records),
            "max_records": self.max_records,
            "latest_ts": self._records[-1]["ts"] if self._records else None,
            "vector_backend": self._vector_status,
            "vector_dim": self.vector_dim,
            "vector_records": vector_count,
        }

    def query(self, text: str, top_k: int = 5) -> list[dict[str, Any]]:
        query = text.strip()
        if not query:
            return []
        q_tokens = _tokenize(query)
        hits: list[MemoryHit] = []
        total = len(self._records)
        by_id: dict[str, dict[str, Any]] = {}
        for idx, item in enumerate(self._records):
            rec = self._normalize_record(item)
            by_id[str(rec.get("id", ""))] = rec
            summary = str(rec.get("summary", ""))
            if not summary:
                continue
            s_tokens = _tokenize(summary)
            overlap = len(q_tokens & s_tokens) if q_tokens and s_tokens else 0
            union = len(q_tokens | s_tokens) if q_tokens or s_tokens else 1
            jaccard = overlap / max(1, union)
            contains_bonus = 0.2 if query.lower() in summary.lower() else 0.0
            recency_bonus = (idx + 1) / max(1, total) * 0.05
            score = jaccard + contains_bonus + recency_bonus
            if score <= 0:
                continue
            hits.append(
                MemoryHit(
                    score=score,
                    ts=str(rec.get("ts", "")),
                    session_id=str(rec.get("session_id", "")),
                    turn=int(rec.get("turn", 0) or 0),
                    role=str(rec.get("role", "")),
                    summary=summary,
                    record_id=str(rec.get("id", "")),
                )
            )

        combined: dict[str, MemoryHit] = {hit.record_id: hit for hit in hits}

        if self._vector_index is not None:
            vec_hits = self._vector_index.query(query, top_k=max(20, top_k * 4))
            for item in vec_hits:
                rid = str(item.get("id", "")).strip()
                if not rid:
                    continue
                rec = by_id.get(rid)
                if rec is None:
                    continue
                vec_score = float(item.get("score", 0.0) or 0.0)
                weighted = max(0.0, vec_score) * 0.8
                if rid in combined:
                    existing = combined[rid]
                    existing.score = max(existing.score, existing.score + weighted)
                else:
                    combined[rid] = MemoryHit(
                        score=weighted,
                        ts=str(rec.get("ts", "")),
                        session_id=str(rec.get("session_id", "")),
                        turn=int(rec.get("turn", 0) or 0),
                        role=str(rec.get("role", "")),
                        summary=str(rec.get("summary", "")),
                        record_id=rid,
                    )

        ranked = sorted(combined.values(), key=lambda x: x.score, reverse=True)
        limit = max(1, min(int(top_k), 20))
        return [hit.as_dict() for hit in ranked[:limit]]

    def latest(self, count: int = 5) -> list[dict[str, Any]]:
        n = max(1, min(int(count), 50))
        return [dict(item) for item in self._records[-n:]]
