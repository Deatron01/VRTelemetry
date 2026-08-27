# src/central_server/data_schema.py

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def initialize_data_schema(db_path: str = "CentralServer/central_data.db") -> None:
    """
    Registry of every session ever uploaded from any researcher's machine.
    The actual Parquet bytes live on disk under CentralStorage/; this DB
    tracks provenance, integrity, and links each upload back to a license.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    schema = """
    CREATE TABLE IF NOT EXISTS uploaded_sessions (
        upload_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,              -- matches the session_id from the researcher's local vr_metadata.db
        license_id TEXT NOT NULL,
        activation_id TEXT NOT NULL,
        machine_label TEXT,
        subject_id TEXT,
        original_filename TEXT NOT NULL,
        storage_path TEXT NOT NULL,             -- relative path under CentralStorage/
        file_size_bytes INTEGER,
        sha256_checksum TEXT NOT NULL,
        total_frames INTEGER,
        duration_sec REAL,
        metadata_json TEXT,                     -- full raw session_metadata blob for later querying
        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verified INTEGER DEFAULT 0,             -- checksum re-verified post-write
        UNIQUE(license_id, session_id)          -- idempotency: re-uploading the same session no-ops
    );

    CREATE TABLE IF NOT EXISTS upload_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        upload_id TEXT,
        activation_id TEXT,
        event_type TEXT NOT NULL,               -- received | rejected | duplicate | corrupt
        detail TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS session_logs (
        log_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        license_id TEXT NOT NULL,
        activation_id TEXT NOT NULL,
        storage_path TEXT NOT NULL,
        file_size_bytes INTEGER,
        received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(license_id, session_id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_uploads_license ON uploaded_sessions(license_id);
    CREATE INDEX IF NOT EXISTS idx_uploads_activation ON uploaded_sessions(activation_id);
    CREATE INDEX IF NOT EXISTS idx_uploads_received ON uploaded_sessions(received_at);
    """

    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(schema)
        conn.commit()
        conn.close()
        logger.info(f"Central data schema initialized at {db_path}")
    except sqlite3.Error as e:
        logger.error(f"Failed to initialize central data schema: {e}")
        raise