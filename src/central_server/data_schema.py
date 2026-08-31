# src/central_server/data_schema.py

import logging
import sqlite3
from pathlib import Path

from src.config import get_settings

logger = logging.getLogger(__name__)


def initialize_data_schema(db_path: str | Path | None = None) -> None:
    """
    Registry of every session ever uploaded from any researcher's machine.
    The actual Parquet bytes live on disk under CentralStorage/; this DB
    tracks provenance, integrity, and links each upload back to a license.
    """
    db_path = Path(db_path) if db_path else get_settings().paths.central_data_db
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema = """
    CREATE TABLE IF NOT EXISTS uploaded_sessions (
        upload_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,              -- matches the session_id from the researcher's local vr_metadata.db
        license_id TEXT NOT NULL,
        activation_id TEXT NOT NULL,
        machine_label TEXT,
        subject_id TEXT,
        patient_id TEXT,                       -- links back to the researcher's local patient record, when known
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
    
    CREATE TABLE IF NOT EXISTS synced_patients (
        patient_id TEXT NOT NULL,
        license_id TEXT NOT NULL,
        activation_id TEXT,
        display_name TEXT,
        external_ref TEXT,
        date_of_birth TEXT,
        biological_sex TEXT,
        notes TEXT,

        -- Self-reported health/demographic profile, mirrors PatientManager.HEALTH_PROFILE_FIELDS
        -- on the client — kept here too so the admin dashboard and any cross-license
        -- research analysis can see it without reaching into each client's local DB.
        age_years INTEGER,
        height_cm REAL,
        weight_kg REAL,
        dominant_hand TEXT,
        vr_experience_level TEXT,
        vr_experience_hours_estimate REAL,
        gaming_experience_hours_per_week REAL,
        vision_correction TEXT,
        vision_impairment TEXT,
        motion_sickness_susceptibility TEXT,
        relevant_health_conditions TEXT,

        gdpr_consent_given INTEGER,
        gdpr_consent_version TEXT,
        gdpr_consent_timestamp TEXT,
        gdpr_consent_withdrawn_at TEXT,
        is_anonymized INTEGER DEFAULT 0,
        raw_json TEXT NOT NULL,
        first_received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (license_id, patient_id)
    );

    CREATE INDEX IF NOT EXISTS idx_uploads_license ON uploaded_sessions(license_id);
    CREATE INDEX IF NOT EXISTS idx_uploads_activation ON uploaded_sessions(activation_id);
    CREATE INDEX IF NOT EXISTS idx_uploads_received ON uploaded_sessions(received_at);
    -- idx_uploads_patient is created *after* the patient_id migration below runs,
    -- not here — on a pre-existing DB this executescript() runs before ALTER TABLE
    -- has added the column, and CREATE INDEX on a nonexistent column is a hard
    -- error (unlike CREATE TABLE IF NOT EXISTS, which just no-ops).

    -- Presence/liveness table driving the Admin "Active Clients" view. One row
    -- per activation_id, upserted on every client heartbeat ping. Deliberately
    -- separate from machine_activations (license authority, in licenses.db) —
    -- this is data-plane presence info, not licensing authority.
    CREATE TABLE IF NOT EXISTS client_heartbeats (
        activation_id TEXT PRIMARY KEY,
        license_id TEXT,
        machine_label TEXT,
        app_version TEXT,
        os_platform TEXT,
        status TEXT,                            -- idle | recording | unknown
        pending_sync_count INTEGER DEFAULT 0,
        ip_address TEXT,
        first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_heartbeats_license ON client_heartbeats(license_id);
    CREATE INDEX IF NOT EXISTS idx_heartbeats_last_seen ON client_heartbeats(last_seen_at);
    """

    # Health/demographic columns added to synced_patients after its initial release —
    # (column_name, sqlite_type) pairs, applied as idempotent ALTER TABLE migrations
    # below so an existing central_data.db picks them up without a manual reset.
    _SYNCED_PATIENT_HEALTH_COLUMNS = [
        ("age_years", "INTEGER"),
        ("height_cm", "REAL"),
        ("weight_kg", "REAL"),
        ("dominant_hand", "TEXT"),
        ("vr_experience_level", "TEXT"),
        ("vr_experience_hours_estimate", "REAL"),
        ("gaming_experience_hours_per_week", "REAL"),
        ("vision_correction", "TEXT"),
        ("vision_impairment", "TEXT"),
        ("motion_sickness_susceptibility", "TEXT"),
        ("relevant_health_conditions", "TEXT"),
    ]

    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(schema)
        conn.commit()

        # Idempotent migration for DBs created before patient_id existed on this table.
        try:
            conn.execute("ALTER TABLE uploaded_sessions ADD COLUMN patient_id TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        for column, col_type in _SYNCED_PATIENT_HEALTH_COLUMNS:
            try:
                conn.execute(f"ALTER TABLE synced_patients ADD COLUMN {column} {col_type}")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # Only safe to create this index once the column above is guaranteed to exist.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_patient ON uploaded_sessions(patient_id)"
        )
        conn.commit()

        conn.close()
        logger.info(f"Central data schema initialized at {db_path}")
    except sqlite3.Error as e:
        logger.error(f"Failed to initialize central data schema: {e}")
        raise
