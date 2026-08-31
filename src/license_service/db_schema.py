# src/license_service/db_schema.py

import logging
import sqlite3
from pathlib import Path

from src.config import get_settings

logger = logging.getLogger(__name__)


def initialize_license_schema(db_path: str | Path | None = None) -> None:
    """
    Central authority schema. Deployed on your server, never shipped to researchers.
    SQLite is fine to start; swap the connection layer for Postgres later without
    changing this shape if you outgrow single-file storage.
    """
    db_path = Path(db_path) if db_path else get_settings().paths.licenses_db
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema = """
    CREATE TABLE IF NOT EXISTS organizations (
        org_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        org_id TEXT REFERENCES organizations(org_id),
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT,
        password_salt TEXT,
        display_name TEXT,
        role TEXT NOT NULL DEFAULT 'researcher',   -- researcher | admin
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sessions (
        session_token TEXT PRIMARY KEY,
        user_id TEXT REFERENCES users(user_id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        revoked INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS licenses (
        license_id TEXT PRIMARY KEY,
        license_key TEXT UNIQUE NOT NULL,
        user_id TEXT REFERENCES users(user_id),
        org_id TEXT REFERENCES organizations(org_id),
        plan TEXT NOT NULL DEFAULT 'standard',
        max_seats INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'active',
        issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        revoked_at TIMESTAMP,
        revoked_reason TEXT
    );

    CREATE TABLE IF NOT EXISTS machine_activations (
        activation_id TEXT PRIMARY KEY,
        license_id TEXT REFERENCES licenses(license_id),
        hardware_fingerprint TEXT NOT NULL,
        machine_label TEXT,
        os_platform TEXT,
        app_version TEXT,
        activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_heartbeat_at TIMESTAMP,
        deactivated_at TIMESTAMP,
        is_revoked INTEGER DEFAULT 0,
        UNIQUE(license_id, hardware_fingerprint)
    );

    CREATE TABLE IF NOT EXISTS activation_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        license_id TEXT,
        activation_id TEXT,
        event_type TEXT NOT NULL,
        detail TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(license_key);
    CREATE INDEX IF NOT EXISTS idx_activations_license ON machine_activations(license_id);
    CREATE INDEX IF NOT EXISTS idx_activations_fingerprint ON machine_activations(hardware_fingerprint);
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    """

    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(schema)
        conn.commit()

        # Idempotent migrations for DBs created before these columns existed.
        for stmt in [
            "ALTER TABLE users ADD COLUMN password_hash TEXT",
            "ALTER TABLE users ADD COLUMN password_salt TEXT",
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'researcher'",
        ]:
            try:
                conn.execute(stmt)
                conn.commit()
            except sqlite3.OperationalError:
                pass

        conn.close()
        logger.info(f"License schema initialized at {db_path}")
    except sqlite3.Error as e:
        logger.error(f"Failed to initialize license schema: {e}")
        raise
