# src/infrastructure/persistence/session_repository.py
"""Every SQL statement that touches session_metadata (VRT-11).

Before this, session data was reached three different ways: ``DatabaseManager``
methods, a raw ``sqlite3.connect`` inside the sessions router, and a second raw
connection inside the update handler -- each with its own connection settings,
its own error handling, and its own idea of which columns exist.

The router now knows nothing about SQL. That matters beyond tidiness: the
handler built an ``UPDATE ... SET`` clause by interpolating dictionary keys
straight into the statement. It was not injectable, because Pydantic had already
discarded any key that was not a declared field -- but that guarantee lived two
files away from the interpolation, and nothing stated it. Here the allowlist is
explicit and checked at the point of use.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.infrastructure.persistence.connection import transaction
from src.infrastructure.persistence.migrations import migrate
from src.utils.logger import logger

#: Columns the original schema declared. Everything added since is a numbered
#: migration -- see migrations.MIGRATIONS -- so this list is history, not the
#: current shape of the table. Do not add to it.
_BASELINE_COLUMNS: tuple[str, ...] = (
    "session_id TEXT PRIMARY KEY",
    "start_timestamp_utc TEXT",
    "subject_id TEXT NOT NULL",
    "subject_age INTEGER",
    "subject_biological_sex TEXT",
    "subject_height_cm REAL",
    "subject_weight_kg REAL",
    "subject_vr_exp TEXT",
    "subject_ipd_mm REAL",
    "vision_correction TEXT",
    "vision_impairment TEXT",
    "tracking_space_type TEXT",
    "play_area_width_m REAL",
    "play_area_length_m REAL",
    "host_os_version TEXT",
    "host_cpu_model TEXT",
    "host_gpu_model TEXT",
    "host_ram_gb REAL",
    "gpu_driver_version TEXT",
    "openxr_runtime TEXT",
    "hmd_model TEXT",
    "hmd_firmware TEXT",
    "hmd_refresh_rate REAL",
    "hmd_render_res_w INTEGER",
    "hmd_render_res_h INTEGER",
    "hmd_fov_horizontal REAL",
    "hmd_fov_vertical REAL",
    "tracking_system TEXT",
    "controller_model TEXT",
    "has_eye_tracking INTEGER",
    "has_face_tracking INTEGER",
    "has_body_tracking INTEGER",
    "neutral_head_height REAL",
    "shoulder_width_est REAL",
    "arm_length_left REAL",
    "arm_length_right REAL",
    "dominant_hand TEXT",
    "ssq_nausea_score REAL",
    "ssq_oculomotor_score REAL",
    "ssq_disorientation REAL",
    "nasa_tlx_mental REAL",
    "nasa_tlx_physical REAL",
    "nasa_tlx_frustration REAL",
    "perceived_temp_c REAL",
    "session_rating INTEGER",
    "preprocessor_version TEXT",
    "smoothing_algorithm TEXT",
    "scaling_method TEXT",
    "velocity_deriv_method TEXT",
    "outlier_removal TEXT",
    "total_dropped_frames INTEGER",
    "raw_json TEXT",
    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "os_name TEXT",
    "os_version TEXT",
    "os_release TEXT",
    "architecture TEXT",
    "hostname TEXT",
    "os_user TEXT",
    "cpu_name TEXT",
    "cpu_cores_logical INTEGER",
    "cpu_cores_physical INTEGER",
    "total_ram_gb REAL",
    "disk_total_gb REAL",
    "disk_free_gb REAL",
    "gpu_info TEXT",
    "app_version TEXT",
)


class SessionRepository:
    """Reads and writes session_metadata.

    Rows come back as plain dicts rather than typed models. That is a deliberate
    scope decision, not an oversight: these dicts are serialised directly into
    API responses, so changing their shape changes the wire contract -- sqlite
    integers 0/1 would become JSON booleans, for one. The frontend currently
    relies on JavaScript truthiness and would survive it, but "would survive it"
    is not something to assert without generated types on the other side.
    VRT-18 generates those from the OpenAPI schema; the typed models land there,
    where the change is checkable rather than hopeful.
    """

    #: The only columns PUT /api/sessions/{id} may write. Previously implicit:
    #: whatever fields SessionUpdate happened to declare, interpolated into the
    #: statement by the handler.
    EDITABLE_COLUMNS: frozenset[str] = frozenset(
        {
            "subject_id",
            "start_timestamp_utc",
            "subject_vr_exp",
            "session_rating",
            "subject_ipd_mm",
            "neutral_head_height",
            "shoulder_width_est",
            "arm_length_left",
            "arm_length_right",
            "dominant_hand",
        }
    )

    #: The columns a scored questionnaire may write.
    QUESTIONNAIRE_COLUMNS: frozenset[str] = frozenset(
        {
            "ssq_nausea_score",
            "ssq_oculomotor_score",
            "ssq_disorientation",
            "ssq_total_severity",
            "ssq_severity_band",
            "ssq_raw_items_json",
            "nasa_tlx_mental",
            "nasa_tlx_physical",
            "nasa_tlx_temporal",
            "nasa_tlx_performance",
            "nasa_tlx_effort",
            "nasa_tlx_frustration",
            "nasa_tlx_rtlx",
            "nasa_tlx_band",
            "nasa_tlx_raw_items_json",
            "thermal_comfort",
            "perceived_temp_c",
            "session_rating",
            "questionnaire_completed_at",
        }
    )

    #: Projection the session list returns. Named explicitly because the
    #: frontend's table reads exactly these keys.
    LISTING_COLUMNS = (
        "session_id",
        "patient_id",
        "start_timestamp_utc",
        "subject_id",
        "hmd_model",
        "tracking_space_type",
        "total_dropped_frames",
        "session_rating",
    )

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Open (and migrate) the session metadata database.

        Args:
            db_path: Override the configured location. Chiefly for tests.
        """
        from src.config import get_settings

        self.db_path = Path(db_path) if db_path else get_settings().paths.metadata_db
        migrate(self.db_path, baseline_schema=self._create_baseline)

    @staticmethod
    def _create_baseline(conn: sqlite3.Connection) -> None:
        """Create session_metadata as it was originally declared.

        Only ever called for a database that does not have the table yet;
        migration 2 onwards brings it up to date from there. Splitting it this
        way means a new install and a five-month-old one converge on the same
        schema by the same path, which the old CREATE-plus-fourteen-ALTERs
        could not guarantee -- and did not.
        """
        columns = ",\n            ".join(_BASELINE_COLUMNS)
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS session_metadata (\n            {columns}\n        )"
        )

    # --- reads -------------------------------------------------------------

    def list_for_api(self) -> list[dict[str, Any]]:
        """Sessions for the main listing, newest first."""
        columns = ", ".join(self.LISTING_COLUMNS)
        try:
            with transaction(self.db_path) as conn:
                # LISTING_COLUMNS is a class-level tuple of literals; nothing
                # here is caller-supplied.
                statement = f"SELECT {columns} FROM session_metadata ORDER BY created_at DESC"  # noqa: S608
                return list(conn.execute(statement))
        except sqlite3.Error as exc:
            logger.error(f"Failed to list sessions: {exc}")
            raise

    def list_all(self) -> list[dict[str, Any]]:
        """Every session this machine knows about, oldest first.

        The source of truth for the backfill sweep, which needs sessions that
        were recorded locally but never pushed -- including ones that predate
        the upload queue entirely.
        """
        try:
            with transaction(self.db_path) as conn:
                return list(
                    conn.execute(
                        "SELECT session_id, patient_id, subject_id, start_timestamp_utc, "
                        "total_dropped_frames, created_at "
                        "FROM session_metadata ORDER BY created_at ASC"
                    )
                )
        except sqlite3.Error as exc:
            logger.error(f"Failed to list all sessions: {exc}")
            return []

    def list_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        """Sessions linked to one patient, most recent first."""
        try:
            with transaction(self.db_path) as conn:
                return list(
                    conn.execute(
                        "SELECT session_id, start_timestamp_utc, hmd_model, "
                        "total_dropped_frames, session_rating, created_at "
                        "FROM session_metadata WHERE patient_id = ? ORDER BY created_at DESC",
                        (patient_id,),
                    )
                )
        except sqlite3.Error as exc:
            logger.error(f"Failed to fetch sessions for patient {patient_id}: {exc}")
            return []

    def session_ids_for_patient(self, patient_id: str) -> list[str]:
        """Every session id linked to one patient, for erasure (GDPR-10).

        Unlike :meth:`list_for_patient`, this does not turn a database error
        into an empty list. For a listing that is a reasonable degradation; for
        an erasure it would report "0 sessions erased" while every recording
        stayed on disk, which is worse than failing.
        """
        with transaction(self.db_path) as conn:
            return [
                row["session_id"]
                for row in conn.execute(
                    "SELECT session_id FROM session_metadata WHERE patient_id = ?", (patient_id,)
                )
            ]

    def delete_sessions(self, session_ids: list[str]) -> int:
        """Remove these sessions' metadata rows. Returns how many were removed.

        Raises on a database error, for the reason given above.
        """
        if not session_ids:
            return 0
        placeholders = ", ".join("?" for _ in session_ids)
        with transaction(self.db_path) as conn:
            cursor = conn.execute(
                f"DELETE FROM session_metadata WHERE session_id IN ({placeholders})",  # noqa: S608 - placeholders only
                session_ids,
            )
            return cursor.rowcount

    def get(self, session_id: str) -> dict[str, Any]:
        """The full row, or an empty dict when there is no such session."""
        try:
            with transaction(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM session_metadata WHERE session_id = ?", (session_id,)
                ).fetchone()
                return row or {}
        except sqlite3.Error as exc:
            logger.error(f"Failed to fetch session row {session_id}: {exc}")
            return {}

    # --- writes ------------------------------------------------------------

    def update(self, session_id: str, fields: dict[str, Any]) -> tuple[bool, list[str]]:
        """Update editable columns on an existing session.

        Args:
            session_id: Which session.
            fields: Column-to-value pairs. Anything outside
                :attr:`EDITABLE_COLUMNS` is dropped rather than written.

        Returns:
            ``(row_was_updated, columns_actually_written)``. An empty column
            list means nothing in ``fields`` was editable.

        Raises:
            sqlite3.Error: on a database failure. The caller decides what a
                failed write means; swallowing it here is how a silent no-op
                gets reported to the researcher as success.
        """
        return self._guarded_update(session_id, fields, self.EDITABLE_COLUMNS)

    def save_questionnaire(self, session_id: str, fields: dict[str, Any]) -> bool:
        """Persist a scored post-session questionnaire onto an existing row.

        A plain UPDATE rather than another INSERT: the engine that wrote the row
        is long gone by the time a researcher fills the form in.
        """
        try:
            updated, _ = self._guarded_update(session_id, fields, self.QUESTIONNAIRE_COLUMNS)
        except sqlite3.Error as exc:
            logger.error(f"Failed to save questionnaire for session {session_id}: {exc}")
            return False
        return updated

    def _guarded_update(
        self, session_id: str, fields: dict[str, Any], allowed: frozenset[str]
    ) -> tuple[bool, list[str]]:
        """Build and run an UPDATE from an explicit column allowlist.

        The allowlist is the whole point. Column names cannot be parameterised
        in SQL, so a dynamic SET clause has to interpolate them -- which is safe
        only if the set of possible names is closed. Here it is closed by
        ``allowed``, checked immediately above the interpolation, instead of by
        a Pydantic model two files away.
        """
        clean = {key: value for key, value in fields.items() if key in allowed}
        if not clean:
            return False, []

        set_clause = ", ".join(f"{column} = ?" for column in clean)
        values = [*clean.values(), session_id]

        with transaction(self.db_path) as conn:
            # `set_clause` is built only from `allowed`,
            # a frozenset of literals defined in this class, filtered three
            # lines above. Column names cannot be parameterised in SQL; a closed
            # allowlist checked at the point of use is the correct guarantee,
            # and it is now visible here rather than implied by a Pydantic model
            # in another package.
            statement = f"UPDATE session_metadata SET {set_clause} WHERE session_id = ?"  # noqa: S608
            cursor = conn.execute(statement, values)
            return cursor.rowcount > 0, sorted(clean)

    def exists(self, session_id: str) -> bool:
        """Whether a session row exists, without fetching 80 columns to find out."""
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM session_metadata WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row is not None
