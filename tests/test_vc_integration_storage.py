from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from vc_platform.storage import VCPlatformStore


class TestVCIntegrationStorage(unittest.TestCase):
    def test_integration_tables_and_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "vc_platform.db"
            store = VCPlatformStore(db_path)

            connection_id = str(uuid4())
            store.upsert_integration_connection(
                connection_id=connection_id,
                startup_id="acme",
                provider="google_drive",
                mode="byo_oauth",
                status="pending_consent",
                scopes=["scope.a", "scope.b"],
                token_ref="token:abc",
                refresh_token_ref="refresh:def",
                metadata={"hello": "world"},
            )

            connection = store.get_integration_connection(connection_id)
            assert connection is not None
            self.assertEqual(connection["startup_id"], "acme")
            self.assertEqual(connection["provider"], "google_drive")
            self.assertEqual(connection["status"], "pending_consent")
            self.assertEqual(connection["scopes_json"], ["scope.a", "scope.b"])

            listed_connections = store.list_integration_connections(startup_id="acme", provider="google_drive")
            self.assertEqual(len(listed_connections), 1)

            run_id = str(uuid4())
            store.create_integration_sync_run(
                run_id=run_id,
                startup_id="acme",
                provider="google_drive",
                connection_id=connection_id,
                run_mode="dry_run",
                window_from="2026-02-01T00:00:00+00:00",
                window_to="2026-02-20T00:00:00+00:00",
            )
            store.add_integration_document(
                document_id="doc-1",
                run_id=run_id,
                startup_id="acme",
                provider="google_drive",
                source_id="drive:file:1",
                title="series_a.pdf",
                mime_type="application/pdf",
                doc_type="ir_deck",
                confidence=0.91,
                metadata={"path": "VC-REPORT/series_a.pdf"},
            )
            store.finish_integration_sync_run(
                run_id=run_id,
                status="completed",
                summary={"document_count": 1},
            )

            run = store.get_integration_sync_run(run_id)
            assert run is not None
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["summary_json"]["document_count"], 1)
            docs = store.list_integration_documents(run_id=run_id)
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]["doc_type"], "ir_deck")

            confirmation_id = str(uuid4())
            store.create_user_confirmation(
                confirmation_id=confirmation_id,
                startup_id="acme",
                collection_id="col-123",
                channel="telegram",
                message="전송 동의 확인",
            )
            pending = store.list_user_confirmations(startup_id="acme", status="pending")
            self.assertEqual(len(pending), 1)
            store.set_user_confirmation_response(
                confirmation_id=confirmation_id,
                status="confirmed",
                responder="founder",
                response={"response": "confirm"},
            )
            updated = store.get_user_confirmation(confirmation_id)
            assert updated is not None
            self.assertEqual(updated["status"], "confirmed")
            self.assertEqual(updated["response_json"]["response"], "confirm")


if __name__ == "__main__":
    unittest.main()
