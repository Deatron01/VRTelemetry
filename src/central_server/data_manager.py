# src/central_server/data_manager.py

import sqlite3
import hashlib
import json
import shutil
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class CentralDataManager:
    """
    Receives finished session files from researcher machines, verifies the
    uploading activation is a real non-revoked seat, and persists both the
    binary payload and its provenance record.
    """

    def __init__(self, db_path: str = "CentralServer/central_data.db",
                 storage_root: str = "CentralServer/CentralStorage"):
        self.db_path = db_path
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ingest_session(
        self,
        *,
        license_id: str,
        activation_id: str,
        machine_label: str,
        session_id: str,
        original_filename: str,
        file_bytes: bytes,
        metadata: Dict[str, Any],
        ip_address: str = "",
    ) -> Dict[str, Any]:
        """
        Core intake path. Called by the FastAPI route after auth has already
        confirmed the activation is valid — this method assumes trust was
        established upstream and focuses on storage + integrity + idempotency.
        """
        checksum = hashlib.sha256(file_bytes).hexdigest()
        upload_id = str(uuid.uuid4())

        with self._conn() as conn:
            existing = conn.execute(
                "SELECT upload_id, sha256_checksum FROM uploaded_sessions WHERE license_id = ? AND session_id = ?",
                (license_id, session_id)
            ).fetchone()

            if existing:
                if existing["sha256_checksum"] == checksum:
                    self._log_event(conn, existing["upload_id"], activation_id, "duplicate",
                                     "identical re-upload, no-op", ip_address)
                    conn.commit()
                    return {"ok": True, "status": "already_received", "upload_id": existing["upload_id"]}
                else:
                    # Same session_id, different bytes — flag rather than silently overwrite,
                    # since this could indicate corruption or a re-recorded/edited file.
                    self._log_event(conn, existing["upload_id"], activation_id, "rejected",
                                     "checksum mismatch on re-upload of existing session_id", ip_address)
                    conn.commit()
                    return {"ok": False, "reason": "session_id_conflict_different_content"}

            # Store file on disk, namespaced by license so one lab's data never collides with another's
            dest_dir = self.storage_root / license_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / f"{session_id}.parquet"
            dest_path.write_bytes(file_bytes)

            # Re-read and re-hash from disk to catch any write-time corruption before trusting it
            on_disk_checksum = hashlib.sha256(dest_path.read_bytes()).hexdigest()
            verified = 1 if on_disk_checksum == checksum else 0
            if not verified:
                logger.error(f"Checksum mismatch after write for session {session_id}, upload {upload_id}")
                self._log_event(conn, upload_id, activation_id, "corrupt", "post-write checksum mismatch", ip_address)

            conn.execute(
                """INSERT INTO uploaded_sessions
                   (upload_id, session_id, license_id, activation_id, machine_label,
                    subject_id, original_filename, storage_path, file_size_bytes,
                    sha256_checksum, total_frames, duration_sec, metadata_json, verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    upload_id, session_id, license_id, activation_id, machine_label,
                    metadata.get("subject_id"), original_filename,
                    str(dest_path.relative_to(self.storage_root)),
                    len(file_bytes), checksum,
                    metadata.get("total_frames"), metadata.get("duration_sec"),
                    json.dumps(metadata), verified,
                )
            )
            self._log_event(conn, upload_id, activation_id, "received", original_filename, ip_address)
            conn.commit()

        logger.info(f"Ingested session {session_id} ({len(file_bytes)} bytes) from activation {activation_id}")
        return {"ok": True, "status": "received", "upload_id": upload_id, "verified": bool(verified)}

    def list_sessions(self, license_id: Optional[str] = None) -> list:
        with self._conn() as conn:
            if license_id:
                rows = conn.execute(
                    "SELECT * FROM uploaded_sessions WHERE license_id = ? ORDER BY received_at DESC",
                    (license_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM uploaded_sessions ORDER BY received_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_file_path(self, upload_id: str) -> Optional[Path]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT storage_path FROM uploaded_sessions WHERE upload_id = ?", (upload_id,)
            ).fetchone()
            if not row:
                return None
            return self.storage_root / row["storage_path"]

    def _log_event(self, conn, upload_id, activation_id, event_type, detail, ip_address):
        conn.execute(
            """INSERT INTO upload_events (upload_id, activation_id, event_type, detail, ip_address)
               VALUES (?, ?, ?, ?, ?)""",
            (upload_id, activation_id, event_type, detail, ip_address)
        )
        
    def ingest_log(self, *, license_id: str, activation_id: str, session_id: str,
                    file_bytes: bytes) -> Dict[str, Any]:
        log_id = str(uuid.uuid4())
        dest_dir = self.storage_root / license_id / "logs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{session_id}.log"
        dest_path.write_bytes(file_bytes)

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO session_logs (log_id, session_id, license_id, activation_id,
                                              storage_path, file_size_bytes)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(license_id, session_id) DO UPDATE SET
                       storage_path=excluded.storage_path, file_size_bytes=excluded.file_size_bytes""",
                (log_id, session_id, license_id, activation_id,
                 str(dest_path.relative_to(self.storage_root)), len(file_bytes))
            )
            conn.commit()

        logger.info(f"Ingested session log for {session_id} ({len(file_bytes)} bytes)")
        return {"ok": True, "log_id": log_id}

    def get_log_path(self, session_id: str, license_id: str) -> Optional[Path]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT storage_path FROM session_logs WHERE session_id = ? AND license_id = ?",
                (session_id, license_id)
            ).fetchone()
            return (self.storage_root / row["storage_path"]) if row else None