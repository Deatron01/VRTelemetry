# src/license_service/local_cache.py

import logging
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.utils.clock import as_stored, parse_utc, utc_now

logger = logging.getLogger(__name__)


class LocalLicenseCache:
    """
    Lives on the researcher's machine, separate from vr_metadata.db by design —
    this file's only job is 'is this install currently authorized to run' plus
    tracking uploads that couldn't reach the central server yet, and now the
    logged-in account session for this machine.
    """

    def __init__(self, db_path: str | Path | None = None):
        # Resolved at call time, not as a default argument: a default is
        # evaluated once at import and would freeze the path before any
        # configuration could be read. See src/config/settings.py (VRT-6).
        self.db_path = Path(db_path) if db_path else get_settings().paths.license_cache_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS license_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    activation_id TEXT,
                    license_id TEXT,
                    license_key TEXT,
                    machine_label TEXT,
                    hardware_fingerprint TEXT,
                    last_verified_at TIMESTAMP,
                    server_expires_at TIMESTAMP,
                    offline_grace_until TIMESTAMP,
                    status TEXT DEFAULT 'unactivated'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_uploads (
                    session_id TEXT PRIMARY KEY,
                    parquet_path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    last_attempt_at TIMESTAMP,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    session_token TEXT,
                    user_id TEXT,
                    email TEXT,
                    display_name TEXT,
                    logged_in_at TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                            CREATE TABLE IF NOT EXISTS pending_patient_syncs (
                                patient_id TEXT PRIMARY KEY,
                                payload_json TEXT NOT NULL,
                                attempts INTEGER DEFAULT 0,
                                last_attempt_at TIMESTAMP,
                                last_error TEXT,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_session_logs (
                    session_id TEXT PRIMARY KEY,
                    log_path TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    last_attempt_at TIMESTAMP,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Confirmed-synced ledgers. Without these, the backfill sweep (which
            # scans every session ever recorded locally, not just ones that went
            # through the live pending_uploads queue) would have no way to know
            # a session was already pushed successfully and would re-upload it
            # — harmless server-side (checksum dedup), but a waste of bandwidth
            # on every app boot for machines with a lot of history.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS synced_sessions (
                    session_id TEXT PRIMARY KEY,
                    upload_id TEXT,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Erasures the hub has not yet confirmed (GDPR-10). A participant's
            # right to erasure does not lapse because the hub was switched off:
            # the request waits here and is retried like any other upload.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_hub_erasures (
                    patient_id TEXT PRIMARY KEY,
                    session_ids_json TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    last_attempt_at TIMESTAMP,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS synced_session_logs (
                    session_id TEXT PRIMARY KEY,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def save(
        self,
        activation_id: str,
        license_key: str,
        hardware_fingerprint: str,
        license_id: str = None,
        machine_label: str = None,
        server_expires_at: str = None,
        grace_hours: int = 72,
    ) -> None:
        grace_until = as_stored(utc_now() + timedelta(hours=grace_hours))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO license_state (id, activation_id, license_id, license_key, machine_label,
                                            hardware_fingerprint, last_verified_at, server_expires_at,
                                            offline_grace_until, status)
                VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, 'active')
                ON CONFLICT(id) DO UPDATE SET
                    activation_id=excluded.activation_id,
                    license_id=excluded.license_id,
                    machine_label=excluded.machine_label,
                    last_verified_at=CURRENT_TIMESTAMP,
                    server_expires_at=excluded.server_expires_at,
                    offline_grace_until=excluded.offline_grace_until,
                    status='active'
            """,
                (
                    activation_id,
                    license_id,
                    license_key,
                    machine_label,
                    hardware_fingerprint,
                    server_expires_at,
                    grace_until,
                ),
            )
            conn.commit()

    def mark_revoked(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE license_state SET status = 'revoked' WHERE id = 1")
            conn.commit()

    def is_valid_offline(self) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, offline_grace_until FROM license_state WHERE id = 1"
            ).fetchone()
            if not row or row[0] != "active":
                return False
            # An activation with no recorded grace window is not "valid
            # forever"; it is an activation that never wrote one. Previously
            # this raised TypeError on the None rather than returning False.
            grace_until = parse_utc(row[1])
            return grace_until is not None and grace_until > utc_now()

    def get_state(self) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM license_state WHERE id = 1").fetchone()
            return dict(row) if row else None

    # --- Pending upload queue ---

    def queue_pending_upload(self, session_id: str, parquet_path: str, metadata_json: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_uploads (session_id, parquet_path, metadata_json)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    parquet_path=excluded.parquet_path,
                    metadata_json=excluded.metadata_json
            """,
                (session_id, parquet_path, metadata_json),
            )
            conn.commit()

    def record_upload_attempt_failure(self, session_id: str, error: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pending_uploads
                SET attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP, last_error = ?
                WHERE session_id = ?
            """,
                (error, session_id),
            )
            conn.commit()

    def clear_pending_upload(self, session_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM pending_uploads WHERE session_id = ?", (session_id,))
            conn.commit()

    def list_pending_uploads(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM pending_uploads ORDER BY created_at ASC").fetchall()
            return [dict(r) for r in rows]

    def queue_pending_patient_sync(self, patient_id: str, payload_json: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_patient_syncs (patient_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(patient_id) DO UPDATE SET payload_json=excluded.payload_json
            """,
                (patient_id, payload_json),
            )
            conn.commit()

    def record_patient_sync_failure(self, patient_id: str, error: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pending_patient_syncs
                SET attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP, last_error = ?
                WHERE patient_id = ?
            """,
                (error, patient_id),
            )
            conn.commit()

    def clear_pending_patient_sync(self, patient_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM pending_patient_syncs WHERE patient_id = ?", (patient_id,))
            conn.commit()

    def list_pending_patient_syncs(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pending_patient_syncs ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Pending hub erasures (GDPR-10) ---

    def queue_pending_erasure(self, patient_id: str, session_ids_json: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_hub_erasures (patient_id, session_ids_json)
                VALUES (?, ?)
                ON CONFLICT(patient_id) DO UPDATE SET session_ids_json=excluded.session_ids_json
            """,
                (patient_id, session_ids_json),
            )
            conn.commit()

    def record_erasure_failure(self, patient_id: str, error: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pending_hub_erasures
                SET attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP, last_error = ?
                WHERE patient_id = ?
            """,
                (error, patient_id),
            )
            conn.commit()

    def clear_pending_erasure(self, patient_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM pending_hub_erasures WHERE patient_id = ?", (patient_id,))
            conn.commit()

    def list_pending_erasures(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pending_hub_erasures ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Pending session log queue (mirrors pending_uploads) ---
    # The original upload_log() path had no retry queue at all — a log upload
    # that failed was simply lost. This closes that gap so logs get the same
    # "automatically retries in the background" guarantee as sessions/patients.

    def queue_pending_session_log(self, session_id: str, log_path: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_session_logs (session_id, log_path)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET log_path=excluded.log_path
            """,
                (session_id, log_path),
            )
            conn.commit()

    def record_session_log_attempt_failure(self, session_id: str, error: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pending_session_logs
                SET attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP, last_error = ?
                WHERE session_id = ?
            """,
                (error, session_id),
            )
            conn.commit()

    def clear_pending_session_log(self, session_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM pending_session_logs WHERE session_id = ?", (session_id,))
            conn.commit()

    def list_pending_session_logs(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pending_session_logs ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Confirmed-synced ledgers (used by the historical backfill sweep) ---

    def mark_session_synced(self, session_id: str, upload_id: str = "") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO synced_sessions (session_id, upload_id, synced_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    upload_id=excluded.upload_id, synced_at=CURRENT_TIMESTAMP
            """,
                (session_id, upload_id),
            )
            conn.commit()

    def is_session_synced(self, session_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM synced_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row is not None

    def mark_session_log_synced(self, session_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO synced_session_logs (session_id, synced_at)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET synced_at=CURRENT_TIMESTAMP
            """,
                (session_id,),
            )
            conn.commit()

    def is_session_log_synced(self, session_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM synced_session_logs WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row is not None

    # --- Account session (login state) ---
    # Single-row table, same pattern as license_state — one desktop install,
    # one logged-in account at a time.

    def save_session(
        self, session_token: str, user_id: str, email: str, display_name: str = ""
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO account_session (id, session_token, user_id, email, display_name, logged_in_at)
                VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    session_token=excluded.session_token,
                    user_id=excluded.user_id,
                    email=excluded.email,
                    display_name=excluded.display_name,
                    logged_in_at=CURRENT_TIMESTAMP
            """,
                (session_token, user_id, email, display_name),
            )
            conn.commit()

    def get_session(self) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM account_session WHERE id = 1").fetchone()
            return dict(row) if row else None

    def clear_session(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM account_session WHERE id = 1")
            conn.commit()

    # --- Generic app config (e.g. central server address, set once at first login) ---

    def set_config(self, key: str, value: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
                (key, value),
            )
            conn.commit()

    def get_config(self, key: str, default: str | None = None) -> str | None:
        """Read a researcher-set config value, falling back to ``default``.

        The annotation used to read ``default: str = None`` -- an implicit
        Optional that says the opposite of what the body does. mypy flagged it
        once the composition root started depending on the return type.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default
