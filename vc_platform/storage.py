from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_plus_hours_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=max(1, hours))).isoformat()


def _parse_json(value: Any, fallback: Any) -> Any:
    try:
        parsed = json.loads(str(value))
    except Exception:
        return fallback
    return parsed


class VCPlatformStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
        return {str(row["name"]) for row in rows}

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        existing = self._table_columns(conn, table)
        if column in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")  # noqa: S608

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collections (
                    collection_id TEXT PRIMARY KEY,
                    startup_id TEXT NOT NULL,
                    window_from TEXT NOT NULL,
                    window_to TEXT NOT NULL,
                    status TEXT NOT NULL,
                    encrypted_path TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    doc_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    mtime TEXT NOT NULL,
                    PRIMARY KEY (artifact_id, collection_id),
                    FOREIGN KEY (collection_id) REFERENCES collections(collection_id)
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    requested_at TEXT NOT NULL,
                    approved_at TEXT NOT NULL DEFAULT '',
                    dispatched_at TEXT NOT NULL DEFAULT '',
                    approver TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    risk_score REAL NOT NULL DEFAULT 0.0,
                    risk_level TEXT NOT NULL DEFAULT 'low',
                    risk_reasons_json TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY (collection_id) REFERENCES collections(collection_id)
                );

                CREATE TABLE IF NOT EXISTS scope_audits (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_id TEXT NOT NULL,
                    startup_id TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS normalized_records (
                    record_id TEXT PRIMARY KEY,
                    startup_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    schema_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approval_signoffs (
                    signoff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    approval_id TEXT NOT NULL,
                    approver TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(approval_id, approver),
                    FOREIGN KEY (approval_id) REFERENCES approvals(approval_id)
                );

                CREATE TABLE IF NOT EXISTS integration_connections (
                    connection_id TEXT PRIMARY KEY,
                    startup_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'byo_oauth',
                    status TEXT NOT NULL,
                    scopes_json TEXT NOT NULL DEFAULT '[]',
                    token_ref TEXT NOT NULL DEFAULT '',
                    refresh_token_ref TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revoked_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS integration_sync_runs (
                    run_id TEXT PRIMARY KEY,
                    startup_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    run_mode TEXT NOT NULL DEFAULT 'manual',
                    window_from TEXT NOT NULL,
                    window_to TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS integration_documents (
                    document_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    startup_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_confirmations (
                    confirmation_id TEXT PRIMARY KEY,
                    startup_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL DEFAULT 'telegram',
                    message TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    responded_at TEXT NOT NULL DEFAULT '',
                    responder TEXT NOT NULL DEFAULT '',
                    response_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_collections_startup_created ON collections(startup_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_artifacts_collection ON artifacts(collection_id);
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, requested_at);
                CREATE INDEX IF NOT EXISTS idx_scope_audits_startup_created ON scope_audits(startup_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_scope_audits_collection ON scope_audits(collection_id);
                CREATE INDEX IF NOT EXISTS idx_normalized_startup_created ON normalized_records(startup_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_normalized_collection ON normalized_records(collection_id);
                CREATE INDEX IF NOT EXISTS idx_signoffs_approval ON approval_signoffs(approval_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_integration_connections_startup_provider
                    ON integration_connections(startup_id, provider, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_integration_sync_runs_startup_provider
                    ON integration_sync_runs(startup_id, provider, created_at);
                CREATE INDEX IF NOT EXISTS idx_integration_docs_run ON integration_documents(run_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_integration_docs_startup_provider
                    ON integration_documents(startup_id, provider, created_at);
                CREATE INDEX IF NOT EXISTS idx_user_confirmations_status
                    ON user_confirmations(startup_id, status, requested_at);
                """
            )

            # Backward-compatible migrations for already created DBs.
            self._ensure_column(conn, "approvals", "dispatched_at", "dispatched_at TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "approvals", "expires_at", "expires_at TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "approvals", "risk_score", "risk_score REAL NOT NULL DEFAULT 0.0")
            self._ensure_column(conn, "approvals", "risk_level", "risk_level TEXT NOT NULL DEFAULT 'low'")
            self._ensure_column(conn, "approvals", "risk_reasons_json", "risk_reasons_json TEXT NOT NULL DEFAULT '[]'")

    def create_collection(
        self,
        *,
        collection_id: str,
        startup_id: str,
        window_from: str,
        window_to: str,
        status: str,
        encrypted_path: str,
        summary: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO collections(
                    collection_id, startup_id, window_from, window_to, status, encrypted_path, summary_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_id,
                    startup_id,
                    window_from,
                    window_to,
                    status,
                    encrypted_path,
                    json.dumps(summary, ensure_ascii=False),
                    _utc_now_iso(),
                ),
            )

    def set_collection_status(self, collection_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE collections SET status = ? WHERE collection_id = ?",
                (status, collection_id),
            )

    def add_artifact(
        self,
        *,
        artifact_id: str,
        collection_id: str,
        rel_path: str,
        sha256: str,
        size_bytes: int,
        doc_type: str,
        confidence: float,
        mtime: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts(
                    artifact_id, collection_id, rel_path, sha256, size_bytes, doc_type, confidence, mtime
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    collection_id,
                    rel_path,
                    sha256,
                    int(size_bytes),
                    doc_type,
                    float(confidence),
                    mtime,
                ),
            )

    def create_approval(
        self,
        *,
        approval_id: str,
        collection_id: str,
        action_type: str,
        payload: dict[str, Any],
        status: str = "pending",
        risk_score: float = 0.0,
        risk_level: str = "low",
        risk_reasons: list[str] | None = None,
        expires_hours: int = 48,
    ) -> None:
        requested_at = _utc_now_iso()
        expires_at = _utc_plus_hours_iso(expires_hours)
        risk_reasons_payload = list(risk_reasons or [])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals(
                    approval_id, collection_id, action_type, payload_json, status, reason,
                    requested_at, approved_at, dispatched_at, approver, expires_at, risk_score, risk_level, risk_reasons_json
                )
                VALUES (?, ?, ?, ?, ?, '', ?, '', '', '', ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    collection_id,
                    action_type,
                    json.dumps(payload, ensure_ascii=False),
                    status,
                    requested_at,
                    expires_at,
                    float(max(0.0, min(risk_score, 1.0))),
                    (risk_level or "low").strip().lower(),
                    json.dumps(risk_reasons_payload, ensure_ascii=False),
                ),
            )

    def get_collection(self, collection_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
        if row is None:
            return None
        parsed = dict(row)
        parsed["summary_json"] = _parse_json(parsed.get("summary_json", "{}"), {})
        return parsed

    def list_collections(
        self,
        *,
        startup_id: str,
        window_from: str | None = None,
        window_to: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM collections WHERE startup_id = ?"
        params: list[Any] = [startup_id]
        if window_from:
            query += " AND window_to >= ?"
            params.append(window_from)
        if window_to:
            query += " AND window_from <= ?"
            params.append(window_to)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["summary_json"] = _parse_json(item.get("summary_json", "{}"), {})
            result.append(item)
        return result

    def list_artifacts(self, *, collection_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT artifact_id, collection_id, rel_path, sha256, size_bytes, doc_type, confidence, mtime
                FROM artifacts
                WHERE collection_id = ?
                ORDER BY rel_path ASC
                """,
                (collection_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_scope_audit(
        self,
        *,
        collection_id: str,
        startup_id: str,
        rel_path: str,
        doc_type: str,
        decision: str,
        reason: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scope_audits(
                    collection_id, startup_id, rel_path, doc_type, decision, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_id,
                    startup_id,
                    rel_path,
                    doc_type,
                    decision,
                    reason,
                    _utc_now_iso(),
                ),
            )

    def list_scope_audits(
        self,
        *,
        startup_id: str,
        collection_id: str | None = None,
        decision: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM scope_audits WHERE startup_id = ?"
        params: list[Any] = [startup_id]
        if collection_id:
            query += " AND collection_id = ?"
            params.append(collection_id)
        if decision:
            query += " AND decision = ?"
            params.append(decision)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 2000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def add_normalized_record(
        self,
        *,
        record_id: str,
        startup_id: str,
        collection_id: str,
        artifact_id: str,
        schema_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO normalized_records(
                    record_id, startup_id, collection_id, artifact_id, schema_type, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    startup_id,
                    collection_id,
                    artifact_id,
                    schema_type,
                    json.dumps(payload, ensure_ascii=False),
                    _utc_now_iso(),
                ),
            )

    def list_normalized_records(
        self,
        *,
        startup_id: str | None = None,
        collection_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM normalized_records WHERE 1=1"
        params: list[Any] = []
        if startup_id:
            query += " AND startup_id = ?"
            params.append(startup_id)
        if collection_id:
            query += " AND collection_id = ?"
            params.append(collection_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = _parse_json(item.get("payload_json", "{}"), {})
            result.append(item)
        return result

    def add_approval_signoff(self, *, approval_id: str, approver: str) -> None:
        normalized_approver = approver.strip()
        if not normalized_approver:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO approval_signoffs(approval_id, approver, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    approval_id,
                    normalized_approver,
                    _utc_now_iso(),
                ),
            )

    def list_approval_signoffs(self, *, approval_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signoff_id, approval_id, approver, created_at
                FROM approval_signoffs
                WHERE approval_id = ?
                ORDER BY created_at ASC
                """,
                (approval_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT a.*, c.startup_id
                FROM approvals a
                JOIN collections c ON c.collection_id = a.collection_id
                WHERE a.approval_id = ?
                """,
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        parsed = dict(row)
        parsed["payload_json"] = _parse_json(parsed.get("payload_json", "{}"), {})
        parsed["risk_reasons_json"] = _parse_json(parsed.get("risk_reasons_json", "[]"), [])
        return parsed

    def list_pending_approvals(self, *, startup_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = (
            "SELECT a.*, c.startup_id "
            "FROM approvals a JOIN collections c ON c.collection_id = a.collection_id "
            "WHERE a.status = 'pending' AND (a.expires_at = '' OR a.expires_at > ?)"
        )
        params: list[Any] = [_utc_now_iso()]
        if startup_id:
            query += " AND c.startup_id = ?"
            params.append(startup_id)
        query += " ORDER BY a.risk_score DESC, a.requested_at ASC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = _parse_json(item.get("payload_json", "{}"), {})
            item["risk_reasons_json"] = _parse_json(item.get("risk_reasons_json", "[]"), [])
            result.append(item)
        return result

    def list_approvals(
        self,
        *,
        startup_id: str | None = None,
        status: str | None = None,
        window_from: str | None = None,
        window_to: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT a.*, c.startup_id "
            "FROM approvals a JOIN collections c ON c.collection_id = a.collection_id "
            "WHERE 1=1"
        )
        params: list[Any] = []
        if startup_id:
            query += " AND c.startup_id = ?"
            params.append(startup_id)
        if status:
            query += " AND a.status = ?"
            params.append(status)
        if window_from:
            query += " AND a.requested_at >= ?"
            params.append(window_from)
        if window_to:
            query += " AND a.requested_at <= ?"
            params.append(window_to)
        query += " ORDER BY a.requested_at DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = _parse_json(item.get("payload_json", "{}"), {})
            item["risk_reasons_json"] = _parse_json(item.get("risk_reasons_json", "[]"), [])
            result.append(item)
        return result

    def update_approval_status(
        self,
        *,
        approval_id: str,
        status: str,
        approver: str = "",
        reason: str = "",
    ) -> None:
        approved_at = _utc_now_iso() if status in {"approved", "dispatched"} else ""
        dispatched_at = _utc_now_iso() if status == "dispatched" else ""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, approver = ?, reason = ?, approved_at = ?, dispatched_at = ?
                WHERE approval_id = ?
                """,
                (
                    status,
                    approver.strip(),
                    reason.strip(),
                    approved_at,
                    dispatched_at,
                    approval_id,
                ),
            )

    def upsert_integration_connection(
        self,
        *,
        connection_id: str,
        startup_id: str,
        provider: str,
        mode: str,
        status: str,
        scopes: list[str] | None = None,
        token_ref: str = "",
        refresh_token_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now_iso()
        scopes_payload = list(scopes or [])
        metadata_payload = dict(metadata or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO integration_connections(
                    connection_id, startup_id, provider, mode, status, scopes_json,
                    token_ref, refresh_token_ref, metadata_json, created_at, updated_at, revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                ON CONFLICT(connection_id) DO UPDATE SET
                    startup_id=excluded.startup_id,
                    provider=excluded.provider,
                    mode=excluded.mode,
                    status=excluded.status,
                    scopes_json=excluded.scopes_json,
                    token_ref=excluded.token_ref,
                    refresh_token_ref=excluded.refresh_token_ref,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    connection_id,
                    startup_id,
                    provider,
                    mode,
                    status,
                    json.dumps(scopes_payload, ensure_ascii=False),
                    token_ref,
                    refresh_token_ref,
                    json.dumps(metadata_payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def get_integration_connection(self, connection_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM integration_connections WHERE connection_id = ?",
                (connection_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["scopes_json"] = _parse_json(item.get("scopes_json", "[]"), [])
        item["metadata_json"] = _parse_json(item.get("metadata_json", "{}"), {})
        return item

    def list_integration_connections(
        self,
        *,
        startup_id: str | None = None,
        provider: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM integration_connections WHERE 1=1"
        params: list[Any] = []
        if startup_id:
            query += " AND startup_id = ?"
            params.append(startup_id)
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 2000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["scopes_json"] = _parse_json(item.get("scopes_json", "[]"), [])
            item["metadata_json"] = _parse_json(item.get("metadata_json", "{}"), {})
            result.append(item)
        return result

    def set_integration_connection_status(
        self,
        *,
        connection_id: str,
        status: str,
        reason: str = "",
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM integration_connections WHERE connection_id = ?",
                (connection_id,),
            ).fetchone()
            if row is None:
                return
            metadata = _parse_json(row["metadata_json"], {})
            if not isinstance(metadata, dict):
                metadata = {}
            if reason.strip():
                metadata["status_reason"] = reason.strip()
            revoked_at = now if status == "revoked" else ""
            conn.execute(
                """
                UPDATE integration_connections
                SET status = ?, updated_at = ?, revoked_at = ?, metadata_json = ?
                WHERE connection_id = ?
                """,
                (
                    status,
                    now,
                    revoked_at,
                    json.dumps(metadata, ensure_ascii=False),
                    connection_id,
                ),
            )

    def create_integration_sync_run(
        self,
        *,
        run_id: str,
        startup_id: str,
        provider: str,
        connection_id: str,
        run_mode: str,
        window_from: str,
        window_to: str,
        status: str = "running",
        summary: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO integration_sync_runs(
                    run_id, startup_id, provider, connection_id, run_mode, window_from, window_to,
                    status, summary_json, error, created_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, '')
                """,
                (
                    run_id,
                    startup_id,
                    provider,
                    connection_id,
                    run_mode,
                    window_from,
                    window_to,
                    status,
                    json.dumps(summary or {}, ensure_ascii=False),
                    _utc_now_iso(),
                ),
            )

    def finish_integration_sync_run(
        self,
        *,
        run_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE integration_sync_runs
                SET status = ?, summary_json = ?, error = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    json.dumps(summary or {}, ensure_ascii=False),
                    error.strip(),
                    _utc_now_iso(),
                    run_id,
                ),
            )

    def get_integration_sync_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM integration_sync_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["summary_json"] = _parse_json(item.get("summary_json", "{}"), {})
        return item

    def list_integration_sync_runs(
        self,
        *,
        startup_id: str | None = None,
        provider: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM integration_sync_runs WHERE 1=1"
        params: list[Any] = []
        if startup_id:
            query += " AND startup_id = ?"
            params.append(startup_id)
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 2000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["summary_json"] = _parse_json(item.get("summary_json", "{}"), {})
            result.append(item)
        return result

    def add_integration_document(
        self,
        *,
        document_id: str,
        run_id: str,
        startup_id: str,
        provider: str,
        source_id: str,
        title: str,
        mime_type: str,
        doc_type: str,
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO integration_documents(
                    document_id, run_id, startup_id, provider, source_id, title, mime_type,
                    doc_type, confidence, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    run_id,
                    startup_id,
                    provider,
                    source_id,
                    title,
                    mime_type,
                    doc_type,
                    float(max(0.0, min(confidence, 1.0))),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    _utc_now_iso(),
                ),
            )

    def list_integration_documents(
        self,
        *,
        run_id: str | None = None,
        startup_id: str | None = None,
        provider: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM integration_documents WHERE 1=1"
        params: list[Any] = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if startup_id:
            query += " AND startup_id = ?"
            params.append(startup_id)
        if provider:
            query += " AND provider = ?"
            params.append(provider)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata_json"] = _parse_json(item.get("metadata_json", "{}"), {})
            result.append(item)
        return result

    def create_user_confirmation(
        self,
        *,
        confirmation_id: str,
        startup_id: str,
        collection_id: str = "",
        channel: str = "telegram",
        message: str = "",
        status: str = "pending",
        response: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_confirmations(
                    confirmation_id, startup_id, collection_id, channel, message,
                    status, requested_at, responded_at, responder, response_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?)
                """,
                (
                    confirmation_id,
                    startup_id,
                    collection_id,
                    channel,
                    message,
                    status,
                    _utc_now_iso(),
                    json.dumps(response or {}, ensure_ascii=False),
                ),
            )

    def get_user_confirmation(self, confirmation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["response_json"] = _parse_json(item.get("response_json", "{}"), {})
        return item

    def list_user_confirmations(
        self,
        *,
        startup_id: str | None = None,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM user_confirmations WHERE 1=1"
        params: list[Any] = []
        if startup_id:
            query += " AND startup_id = ?"
            params.append(startup_id)
        if collection_id:
            query += " AND collection_id = ?"
            params.append(collection_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY requested_at DESC LIMIT ?"
        params.append(max(1, min(limit, 2000)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["response_json"] = _parse_json(item.get("response_json", "{}"), {})
            result.append(item)
        return result

    def set_user_confirmation_response(
        self,
        *,
        confirmation_id: str,
        status: str,
        responder: str = "",
        response: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_confirmations
                SET status = ?, responded_at = ?, responder = ?, response_json = ?
                WHERE confirmation_id = ?
                """,
                (
                    status,
                    _utc_now_iso(),
                    responder.strip(),
                    json.dumps(response or {}, ensure_ascii=False),
                    confirmation_id,
                ),
            )
