# src/license_service/local_cache.py

import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class LocalLicenseCache:
    """
    Lives on the researcher's machine, separate from vr_metadata.db by design —
    this file's only job is 'is this install currently authorized to run' plus
    tracking uploads that couldn't reach the central server yet.
    """

    def __init__(self, db_path: str = "AppData/license_cache.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
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
            conn.commit()

    def save(self, activation_id: str, license_key: str, hardware_fingerprint: str,
              license_id: str = None, machine_label: str = None,
              server_expires_at: str = None, grace_hours: int = 72) -> None:
        grace_until = (datetime.utcnow() + timedelta(hours=grace_hours)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
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
            """, (activation_id, license_id, license_key, machine_label,
                  hardware_fingerprint, server_expires_at, grace_until))
            conn.commit()

    def mark_revoked(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE license_state SET status = 'revoked' WHERE id = 1")
            conn.commit()

    def is_valid_offline(self) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT status, offline_grace_until FROM license_state WHERE id = 1").fetchone()
            if not row or row[0] != 'active':
                return False
            return datetime.fromisoformat(row[1]) > datetime.utcnow()

    def get_state(self) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM license_state WHERE id = 1").fetchone()
            return dict(row) if row else None

    # --- Pending upload queue ---
    # A session lands here whenever an upload attempt fails (offline, server down,
    # transient LAN hiccup). Nothing is ever silently dropped — it's retried on
    # the next engine start and can also be retried on demand via the Export page.

    def queue_pending_upload(self, session_id: str, parquet_path: str, metadata_json: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO pending_uploads (session_id, parquet_path, metadata_json)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    parquet_path=excluded.parquet_path,
                    metadata_json=excluded.metadata_json
            """, (session_id, parquet_path, metadata_json))
            conn.commit()

    def record_upload_attempt_failure(self, session_id: str, error: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE pending_uploads
                SET attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP, last_error = ?
                WHERE session_id = ?
            """, (error, session_id))
            conn.commit()

    def clear_pending_upload(self, session_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM pending_uploads WHERE session_id = ?", (session_id,))
            conn.commit()

    def list_pending_uploads(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM pending_uploads ORDER BY created_at ASC").fetchall()
            return [dict(r) for r in rows]