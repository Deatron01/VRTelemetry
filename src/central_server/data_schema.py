# src/central_server/data_schema.py

import json
import logging
import sqlite3
from pathlib import Path

from src.central_server.plugin_catalog import load_catalog as load_json_seed_catalog
from src.config import get_settings
from src.domain.hub_projection import project_patient_for_hub, project_session_metadata_for_hub
from src.utils.clock import utc_today

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

    -- The operator-curated plugin allowlist GET /api/plugins/catalog serves to
    -- workstations, promoted from the flat plugin_catalog.json file (see that
    -- module's docstring) to a real table so the admin dashboard can add,
    -- publish/unpublish and delete entries instead of an operator hand-editing
    -- JSON and redeploying. `published` gates visibility on the public route --
    -- an unpublished row exists for an admin to stage or review but is never
    -- returned to a workstation, which is what makes "add" and "publish"
    -- meaningfully different actions rather than one action with two names.
    CREATE TABLE IF NOT EXISTS plugin_catalog (
        plugin_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        repo_url TEXT NOT NULL,
        ref TEXT NOT NULL DEFAULT 'main',
        homepage TEXT,
        maintainer TEXT,
        published INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
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

        scrubbed = scrub_identifying_data(conn)
        if scrubbed:
            logger.warning(
                f"GDPR-11: removed participant identifiers from {scrubbed} hub record(s) "
                f"written before the hub projection existed."
            )

        seed_plugin_catalog_from_json(conn)

        conn.close()
        logger.info(f"Central data schema initialized at {db_path}")
    except sqlite3.Error as e:
        logger.error(f"Failed to initialize central data schema: {e}")
        raise


def seed_plugin_catalog_from_json(conn: sqlite3.Connection) -> int:
    """One-time migration: import plugin_catalog.json into the plugin_catalog
    table the first time it's ever empty.

    Only fires on an empty table, not "any entry missing" -- an admin who
    deliberately deleted every catalog entry through the admin UI must not
    have them silently reappear on the next server restart. Seeded rows are
    marked ``published=1`` immediately: they were already being served live
    from the JSON file before this table existed, so seeding them as
    unpublished drafts would read as an unannounced catalog outage, not a
    safer default.

    Returns the number of rows seeded (0 on every run after the first).
    """
    (count,) = conn.execute("SELECT COUNT(*) FROM plugin_catalog").fetchone()
    if count:
        return 0

    seeded = 0
    for entry in load_json_seed_catalog():
        conn.execute(
            """INSERT OR IGNORE INTO plugin_catalog
                   (plugin_id, name, description, repo_url, ref, homepage, maintainer, published)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                entry.plugin_id,
                entry.name,
                entry.description,
                entry.repo_url,
                entry.ref,
                entry.homepage,
                entry.maintainer,
            ),
        )
        seeded += 1
    if seeded:
        conn.commit()
        logger.info(
            f"Seeded {seeded} plugin(s) from plugin_catalog.json into the plugin_catalog table."
        )
    return seeded


def scrub_identifying_data(conn: sqlite3.Connection) -> int:
    """Remove participant identifiers from rows written before GDPR-11.

    Until the hub projection existed, workstations sent the whole patient
    record and stamped the participant's display name on every session as its
    ``subject_id``. New writes are projected on receipt; this brings rows that
    are already on disk into line. It is idempotent: a second run finds nothing
    to change and returns 0, so it runs on every start rather than being
    tracked as a one-off migration.

    Order matters. Session ``subject_id`` values are compared against
    ``synced_patients.display_name`` *before* that column is cleared, because
    afterwards there is nothing left to recognise a name by.

    Args:
        conn: An open connection to ``central_data.db``.

    Returns:
        The number of rows changed.
    """
    changed = 0
    changed += conn.execute(
        """UPDATE uploaded_sessions SET subject_id = patient_id
           WHERE patient_id IS NOT NULL AND subject_id IN (
               SELECT p.display_name FROM synced_patients p
               WHERE p.patient_id = uploaded_sessions.patient_id
                 AND p.license_id = uploaded_sessions.license_id
                 AND p.display_name IS NOT NULL AND p.display_name != ''
           )"""
    ).rowcount

    today = utc_today()
    rows = conn.execute(
        """SELECT rowid, raw_json, date_of_birth FROM synced_patients
           WHERE display_name IS NOT NULL OR external_ref IS NOT NULL
              OR date_of_birth IS NOT NULL OR notes IS NOT NULL
              OR vision_impairment IS NOT NULL OR relevant_health_conditions IS NOT NULL"""
    ).fetchall()
    for rowid, raw_json, date_of_birth in rows:
        try:
            full = json.loads(raw_json) if raw_json else {}
        except ValueError:
            full = {}
        if date_of_birth and "date_of_birth" not in full:
            full["date_of_birth"] = date_of_birth
        projected = project_patient_for_hub(full, today)
        conn.execute(
            """UPDATE synced_patients SET
                   display_name = NULL, external_ref = NULL, date_of_birth = NULL,
                   notes = NULL, vision_impairment = NULL,
                   relevant_health_conditions = NULL,
                   age_years = COALESCE(?, age_years),
                   raw_json = ?
               WHERE rowid = ?""",
            (projected.get("age_years"), json.dumps(projected), rowid),
        )
        changed += 1

    for upload_id, metadata_json in conn.execute(
        "SELECT upload_id, metadata_json FROM uploaded_sessions WHERE metadata_json IS NOT NULL"
    ).fetchall():
        try:
            metadata = json.loads(metadata_json)
        except ValueError:
            continue
        projected_json = json.dumps(project_session_metadata_for_hub(metadata))
        if projected_json != json.dumps(metadata):
            conn.execute(
                "UPDATE uploaded_sessions SET metadata_json = ? WHERE upload_id = ?",
                (projected_json, upload_id),
            )
            changed += 1

    conn.commit()
    return changed
