# src/central_server/data_manager.py

import hashlib
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.domain.hub_projection import (
    project_patient_for_hub,
    project_session_metadata_for_hub,
)
from src.utils.clock import utc_today

logger = logging.getLogger(__name__)


class CentralDataManager:
    """
    Receives finished session files from researcher machines, verifies the
    uploading activation is a real non-revoked seat, and persists both the
    binary payload and its provenance record.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        storage_root: str | Path | None = None,
    ):
        paths = get_settings().paths
        self.db_path = Path(db_path) if db_path else paths.central_data_db
        self.storage_root = Path(storage_root) if storage_root else paths.central_storage_dir
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
        metadata: dict[str, Any],
        ip_address: str = "",
    ) -> dict[str, Any]:
        """
        Core intake path. Called by the FastAPI route after auth has already
        confirmed the activation is valid — this method assumes trust was
        established upstream and focuses on storage + integrity + idempotency.

        Metadata is projected on receipt (GDPR-11) even though current clients
        project before sending: the hub must not depend on every workstation
        running a version that does.
        """
        metadata = project_session_metadata_for_hub(metadata)
        checksum = hashlib.sha256(file_bytes).hexdigest()
        upload_id = str(uuid.uuid4())

        with self._conn() as conn:
            existing = conn.execute(
                "SELECT upload_id, sha256_checksum FROM uploaded_sessions WHERE license_id = ? AND session_id = ?",
                (license_id, session_id),
            ).fetchone()

            if existing:
                if existing["sha256_checksum"] == checksum:
                    self._log_event(
                        conn,
                        existing["upload_id"],
                        activation_id,
                        "duplicate",
                        "identical re-upload, no-op",
                        ip_address,
                    )
                    conn.commit()
                    return {
                        "ok": True,
                        "status": "already_received",
                        "upload_id": existing["upload_id"],
                    }
                else:
                    # Same session_id, different bytes — flag rather than silently overwrite,
                    # since this could indicate corruption or a re-recorded/edited file.
                    self._log_event(
                        conn,
                        existing["upload_id"],
                        activation_id,
                        "rejected",
                        "checksum mismatch on re-upload of existing session_id",
                        ip_address,
                    )
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
                logger.error(
                    f"Checksum mismatch after write for session {session_id}, upload {upload_id}"
                )
                self._log_event(
                    conn,
                    upload_id,
                    activation_id,
                    "corrupt",
                    "post-write checksum mismatch",
                    ip_address,
                )

            conn.execute(
                """INSERT INTO uploaded_sessions
                   (upload_id, session_id, license_id, activation_id, machine_label,
                    subject_id, patient_id, original_filename, storage_path, file_size_bytes,
                    sha256_checksum, total_frames, duration_sec, metadata_json, verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    upload_id,
                    session_id,
                    license_id,
                    activation_id,
                    machine_label,
                    metadata.get("subject_id"),
                    metadata.get("patient_id"),
                    original_filename,
                    str(dest_path.relative_to(self.storage_root)),
                    len(file_bytes),
                    checksum,
                    metadata.get("total_frames"),
                    metadata.get("duration_sec"),
                    json.dumps(metadata),
                    verified,
                ),
            )
            self._log_event(
                conn, upload_id, activation_id, "received", original_filename, ip_address
            )
            conn.commit()

        logger.info(
            f"Ingested session {session_id} ({len(file_bytes)} bytes) from activation {activation_id}"
        )
        return {
            "ok": True,
            "status": "received",
            "upload_id": upload_id,
            "verified": bool(verified),
        }

    def list_sessions(self, license_id: str | None = None) -> list:
        with self._conn() as conn:
            if license_id:
                rows = conn.execute(
                    "SELECT * FROM uploaded_sessions WHERE license_id = ? ORDER BY received_at DESC",
                    (license_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM uploaded_sessions ORDER BY received_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def update_session_metadata(
        self, *, license_id: str, session_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Overwrites metadata_json on an already-ingested session without touching
        the stored Parquet bytes or its checksum. Exists for the post-session
        questionnaire flow: SSQ/NASA-TLX scores are captured client-side *after*
        recording stops (and often after the session already synced), so there's
        no new file to upload — just an updated metadata record. ingest_session()
        can't be reused for this because it's checksum-gated on file bytes: a
        second call with identical parquet bytes short-circuits as "already
        received" and never looks at the metadata argument again.
        """
        metadata = project_session_metadata_for_hub(metadata)
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE uploaded_sessions SET metadata_json = ? WHERE license_id = ? AND session_id = ?",
                (json.dumps(metadata), license_id, session_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return {"ok": False, "reason": "session_not_found"}
            return {"ok": True, "status": "metadata_updated"}

    def get_file_path(self, upload_id: str) -> Path | None:
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
            (upload_id, activation_id, event_type, detail, ip_address),
        )

    def ingest_log(
        self, *, license_id: str, activation_id: str, session_id: str, file_bytes: bytes
    ) -> dict[str, Any]:
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
                (
                    log_id,
                    session_id,
                    license_id,
                    activation_id,
                    str(dest_path.relative_to(self.storage_root)),
                    len(file_bytes),
                ),
            )
            conn.commit()

        logger.info(f"Ingested session log for {session_id} ({len(file_bytes)} bytes)")
        return {"ok": True, "log_id": log_id}

    def erase_patient(
        self,
        *,
        license_id: str,
        activation_id: str,
        patient_id: str,
        session_ids: list[str],
        ip_address: str = "",
    ) -> dict[str, Any]:
        """Delete everything this hub holds for one patient of one tenant (GDPR-10).

        Sessions are found by patient id *and* by the session ids the
        workstation sends, because a session backfilled without its metadata
        row was uploaded with no patient link at all. Both lookups are scoped
        to ``license_id``, which the route derives from the authorised
        activation -- one tenant can never erase another's data.

        Files are deleted before rows. A file that cannot be deleted (on
        Windows, most often because something holds it open) keeps its row, so
        the erasure is reported as incomplete and the workstation's retry finds
        it again, instead of the row disappearing and the file being orphaned
        where nothing will ever look for it.

        Returns:
            Counts of what was removed, and ``complete``.
        """
        placeholders = ", ".join("?" for _ in session_ids) or "NULL"
        with self._conn() as conn:
            uploads = conn.execute(
                f"""SELECT upload_id, session_id, storage_path FROM uploaded_sessions
                    WHERE license_id = ? AND (patient_id = ? OR session_id IN ({placeholders}))""",
                (license_id, patient_id, *session_ids),
            ).fetchall()
            all_session_ids = sorted({r["session_id"] for r in uploads} | set(session_ids))
            log_placeholders = ", ".join("?" for _ in all_session_ids) or "NULL"
            logs = conn.execute(
                f"""SELECT log_id, storage_path FROM session_logs
                    WHERE license_id = ? AND session_id IN ({log_placeholders})""",
                (license_id, *all_session_ids),
            ).fetchall()

            failed: list[str] = []
            deleted = {"uploaded_sessions": 0, "session_logs": 0}
            for table, key, rows in (
                ("uploaded_sessions", "upload_id", uploads),
                ("session_logs", "log_id", logs),
            ):
                for row in rows:
                    path = self.storage_root / row["storage_path"]
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as exc:
                        failed.append(row["storage_path"])
                        logger.error(f"Erasure could not delete {row['storage_path']}: {exc}")
                        continue
                    conn.execute(f"DELETE FROM {table} WHERE {key} = ?", (row[key],))
                    deleted[table] += 1

            patient_rows = conn.execute(
                "DELETE FROM synced_patients WHERE license_id = ? AND patient_id = ?",
                (license_id, patient_id),
            ).rowcount
            # Identifiers and counts only: the audit trail must not become a
            # second copy of what was just erased.
            self._log_event(
                conn,
                None,
                activation_id,
                "erased",
                f"patient={patient_id} sessions={len(uploads)} logs={len(logs)} "
                f"failed={len(failed)}",
                ip_address,
            )
            conn.commit()

        logger.warning(
            f"Erased patient {patient_id} under license {license_id}: {len(uploads)} session(s), "
            f"{len(logs)} log(s), {len(failed)} file(s) could not be deleted."
        )
        return {
            "ok": not failed,
            "complete": not failed,
            "sessions_deleted": deleted["uploaded_sessions"],
            "logs_deleted": deleted["session_logs"],
            "patient_record_deleted": bool(patient_rows),
            "failed_files": failed,
        }

    def get_log_path(self, session_id: str, license_id: str) -> Path | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT storage_path FROM session_logs WHERE session_id = ? AND license_id = ?",
                (session_id, license_id),
            ).fetchone()
            return (self.storage_root / row["storage_path"]) if row else None

    # Mirrors PatientManager.HEALTH_PROFILE_FIELDS on the client.
    _HEALTH_PROFILE_FIELDS = (
        "age_years",
        "height_cm",
        "weight_kg",
        "dominant_hand",
        "vr_experience_level",
        "vr_experience_hours_estimate",
        "gaming_experience_hours_per_week",
        "vision_correction",
        "vision_impairment",
        "motion_sickness_susceptibility",
        "relevant_health_conditions",
    )

    def upsert_patient(
        self, *, license_id: str, activation_id: str, patient: dict[str, Any]
    ) -> dict[str, Any]:
        """Store the hub's copy of a patient -- the projection, never the full record.

        ``display_name``, ``external_ref``, ``date_of_birth``, ``notes`` and the
        free-text health fields keep their columns for schema compatibility
        but are always written as NULL (GDPR-11). ``raw_json`` holds the
        projection too, so the admin dashboard's "Full Record" shows exactly
        what the hub is allowed to hold.
        """
        patient = project_patient_for_hub(patient, utc_today())
        health_columns = ", ".join(self._HEALTH_PROFILE_FIELDS)
        health_placeholders = ", ".join("?" for _ in self._HEALTH_PROFILE_FIELDS)
        health_updates = ", ".join(f"{col}=excluded.{col}" for col in self._HEALTH_PROFILE_FIELDS)
        health_values = tuple(patient.get(col) for col in self._HEALTH_PROFILE_FIELDS)

        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO synced_patients (
                    patient_id, license_id, activation_id, display_name, external_ref,
                    date_of_birth, biological_sex, notes,
                    {health_columns},
                    gdpr_consent_given,
                    gdpr_consent_version, gdpr_consent_timestamp, gdpr_consent_withdrawn_at,
                    is_anonymized, raw_json, last_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, {health_placeholders}, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(license_id, patient_id) DO UPDATE SET
                    activation_id=excluded.activation_id,
                    display_name=excluded.display_name,
                    external_ref=excluded.external_ref,
                    date_of_birth=excluded.date_of_birth,
                    biological_sex=excluded.biological_sex,
                    notes=excluded.notes,
                    {health_updates},
                    gdpr_consent_given=excluded.gdpr_consent_given,
                    gdpr_consent_version=excluded.gdpr_consent_version,
                    gdpr_consent_timestamp=excluded.gdpr_consent_timestamp,
                    gdpr_consent_withdrawn_at=excluded.gdpr_consent_withdrawn_at,
                    is_anonymized=excluded.is_anonymized,
                    raw_json=excluded.raw_json,
                    last_updated_at=CURRENT_TIMESTAMP""",
                (
                    patient["patient_id"],
                    license_id,
                    activation_id,
                    patient.get("display_name"),
                    patient.get("external_ref"),
                    patient.get("date_of_birth"),
                    patient.get("biological_sex"),
                    patient.get("notes"),
                    *health_values,
                    patient.get("gdpr_consent_given"),
                    patient.get("gdpr_consent_version"),
                    patient.get("gdpr_consent_timestamp"),
                    patient.get("gdpr_consent_withdrawn_at"),
                    patient.get("is_anonymized", 0),
                    json.dumps(patient),
                ),
            )
            conn.commit()
        logger.info(f"Patient {patient['patient_id']} synced centrally under license {license_id}")
        return {"ok": True}

    def list_patients(self, license_id: str | None = None) -> list:
        """
        Returns every synced patient enriched with a live session_count and
        last_session_at computed from uploaded_sessions — the admin dashboard's
        patient table shouldn't have to guess this from a separate call.
        """
        base_query = """
            SELECT p.*,
                   COUNT(s.upload_id) AS session_count,
                   MAX(s.received_at) AS last_session_at
            FROM synced_patients p
            LEFT JOIN uploaded_sessions s
                ON s.patient_id = p.patient_id AND s.license_id = p.license_id
            {where}
            GROUP BY p.license_id, p.patient_id
            ORDER BY p.last_updated_at DESC
        """
        with self._conn() as conn:
            if license_id:
                rows = conn.execute(
                    base_query.format(where="WHERE p.license_id = ?"), (license_id,)
                ).fetchall()
            else:
                rows = conn.execute(base_query.format(where="")).fetchall()
            return [dict(r) for r in rows]

    # --- Client presence / heartbeats (Active Clients admin tab) ---

    def record_heartbeat(
        self,
        *,
        activation_id: str,
        license_id: str = "",
        machine_label: str = "",
        app_version: str = "",
        os_platform: str = "",
        status: str = "unknown",
        pending_sync_count: int = 0,
        ip_address: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO client_heartbeats (
                    activation_id, license_id, machine_label, app_version, os_platform,
                    status, pending_sync_count, ip_address, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(activation_id) DO UPDATE SET
                    license_id=excluded.license_id,
                    machine_label=excluded.machine_label,
                    app_version=excluded.app_version,
                    os_platform=excluded.os_platform,
                    status=excluded.status,
                    pending_sync_count=excluded.pending_sync_count,
                    ip_address=excluded.ip_address,
                    last_seen_at=CURRENT_TIMESTAMP""",
                (
                    activation_id,
                    license_id,
                    machine_label,
                    app_version,
                    os_platform,
                    status,
                    pending_sync_count,
                    ip_address,
                ),
            )
            conn.commit()

    def list_client_heartbeats(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM client_heartbeats ORDER BY last_seen_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Plugin catalog (admin dashboard's Plugin Catalog tab) -------------
    #
    # Backs both GET /api/plugins/catalog (the public, workstation-facing
    # route -- published_only=True) and the /admin/plugins/* routes the
    # dashboard's Add/Publish/Unpublish/Delete actions call. See
    # data_schema.py's plugin_catalog table comment for why "add" and
    # "publish" are two different actions rather than one.

    def list_plugins(self, *, published_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM plugin_catalog"
        if published_only:
            query += " WHERE published = 1"
        query += " ORDER BY name COLLATE NOCASE ASC"
        with self._conn() as conn:
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM plugin_catalog WHERE plugin_id = ?", (plugin_id,)
            ).fetchone()
            return dict(row) if row else None

    def add_plugin(
        self,
        *,
        plugin_id: str,
        name: str,
        description: str,
        repo_url: str,
        ref: str = "main",
        homepage: str | None = None,
        maintainer: str | None = None,
    ) -> bool:
        """Add a new catalog entry, unpublished by default.

        Returns False (no exception) if ``plugin_id`` already exists -- an
        admin re-submitting the add form, or two admins racing, is an
        ordinary occurrence the route should report as 409, not a server
        error. Never publishes on add: staging an entry before it's visible
        to every workstation is the entire reason this is two actions.
        """
        with self._conn() as conn:
            try:
                conn.execute(
                    """INSERT INTO plugin_catalog
                           (plugin_id, name, description, repo_url, ref, homepage, maintainer, published)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                    (plugin_id, name, description, repo_url, ref, homepage, maintainer),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update_plugin(self, plugin_id: str, **fields: Any) -> bool:
        """Update the editable fields of an existing catalog entry.

        ``fields`` may contain any of name/description/repo_url/ref/
        homepage/maintainer -- unknown keys are ignored rather than raising,
        so a caller can pass a whole form payload through without
        pre-filtering it. Returns False if the plugin doesn't exist or no
        recognised field was supplied.
        """
        editable = {"name", "description", "repo_url", "ref", "homepage", "maintainer"}
        updates = {k: v for k, v in fields.items() if k in editable}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE plugin_catalog SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE plugin_id = ?",
                (*updates.values(), plugin_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def set_plugin_published(self, plugin_id: str, published: bool) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE plugin_catalog SET published = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE plugin_id = ?",
                (1 if published else 0, plugin_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_plugin(self, plugin_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM plugin_catalog WHERE plugin_id = ?", (plugin_id,))
            conn.commit()
            return cur.rowcount > 0
