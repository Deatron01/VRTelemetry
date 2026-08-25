# src/license_service/db_schema.py

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def initialize_license_schema(db_path: str = "LicenseServer/licenses.db") -> None:
    """
    Central authority schema. Deployed on your server, never shipped to researchers.
    SQLite is fine to start; swap the connection layer for Postgres later without
    changing this shape if you outgrow single-file storage.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

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
        display_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS licenses (
        license_id TEXT PRIMARY KEY,
        license_key TEXT UNIQUE NOT NULL,     -- the string a researcher types in to activate
        user_id TEXT REFERENCES users(user_id),
        org_id TEXT REFERENCES organizations(org_id),
        plan TEXT NOT NULL DEFAULT 'standard',
        max_seats INTEGER NOT NULL DEFAULT 1,  -- how many machines may be active at once
        status TEXT NOT NULL DEFAULT 'active', -- active | revoked | expired | suspended
        issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,                  -- NULL = no fixed expiry, subscription-style
        revoked_at TIMESTAMP,
        revoked_reason TEXT
    );

    -- One row per machine a license has ever been activated on.
    -- This is what makes seat limits and per-machine revocation possible.
    CREATE TABLE IF NOT EXISTS machine_activations (
        activation_id TEXT PRIMARY KEY,
        license_id TEXT REFERENCES licenses(license_id),
        hardware_fingerprint TEXT NOT NULL,    -- derived client-side, see fingerprint.py later
        machine_label TEXT,                    -- e.g. "Lab-PC-3", user-editable for their own reference
        os_platform TEXT,
        app_version TEXT,
        activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_heartbeat_at TIMESTAMP,
        deactivated_at TIMESTAMP,              -- set when researcher explicitly deactivates a seat
        is_revoked INTEGER DEFAULT 0,          -- set independently of license-level revocation,
                                                -- so you can kill one machine without killing the whole license
        UNIQUE(license_id, hardware_fingerprint)
    );

    -- Append-only audit trail. Never updated, only inserted — this is your paper trail
    -- for "who did what when" if a license dispute or abuse investigation comes up.
    CREATE TABLE IF NOT EXISTS activation_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        license_id TEXT,
        activation_id TEXT,
        event_type TEXT NOT NULL,              -- activate | heartbeat | deactivate | revoke | reject
        detail TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(license_key);
    CREATE INDEX IF NOT EXISTS idx_activations_license ON machine_activations(license_id);
    CREATE INDEX IF NOT EXISTS idx_activations_fingerprint ON machine_activations(hardware_fingerprint);
    ALTER TABLE license_state ADD COLUMN license_id TEXT;
    ALTER TABLE license_state ADD COLUMN machine_label TEXT;
    """

    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(schema)
        conn.commit()
        conn.close()
        logger.info(f"License schema initialized at {db_path}")
    except sqlite3.Error as e:
        logger.error(f"Failed to initialize license schema: {e}")
        raise