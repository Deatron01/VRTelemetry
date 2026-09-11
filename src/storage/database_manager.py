# src/storage/database_manager.py

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.infrastructure.persistence import SessionRepository, migrate
from src.infrastructure.persistence.connection import transaction

logger = logging.getLogger(__name__)


#: Column order for the session_metadata INSERT, and the single source of truth
#: for it: the statement text and its placeholder list are both derived from
#: this tuple.
#:
#: It is a tuple rather than a hand-maintained SQL string because the
#: hand-maintained version named 68 columns and supplied 73 "?" placeholders.
#: Every call to persist_experiment() therefore raised "73 values for 68
#: columns" and the session's entire metadata row was lost -- on every machine,
#: for every session ever recorded. TelemetryEngine.start() logged the failure
#: and carried on, exactly as it was written to, which is why nobody noticed.
#: See VRT-22.
SESSION_METADATA_COLUMNS: tuple[str, ...] = (
    "session_id",
    "patient_id",
    "start_timestamp_utc",
    "subject_id",
    "subject_age",
    "subject_biological_sex",
    "subject_height_cm",
    "subject_weight_kg",
    "subject_vr_exp",
    "subject_ipd_mm",
    "vision_correction",
    "vision_impairment",
    "tracking_space_type",
    "play_area_width_m",
    "play_area_length_m",
    "host_os_version",
    "host_cpu_model",
    "host_gpu_model",
    "host_ram_gb",
    "gpu_driver_version",
    "openxr_runtime",
    "hmd_model",
    "hmd_firmware",
    "hmd_refresh_rate",
    "hmd_render_res_w",
    "hmd_render_res_h",
    "hmd_fov_horizontal",
    "hmd_fov_vertical",
    "tracking_system",
    "controller_model",
    "has_eye_tracking",
    "has_face_tracking",
    "has_body_tracking",
    "neutral_head_height",
    "shoulder_width_est",
    "arm_length_left",
    "arm_length_right",
    "dominant_hand",
    "ssq_nausea_score",
    "ssq_oculomotor_score",
    "ssq_disorientation",
    "nasa_tlx_mental",
    "nasa_tlx_physical",
    "nasa_tlx_frustration",
    "perceived_temp_c",
    "session_rating",
    "preprocessor_version",
    "smoothing_algorithm",
    "scaling_method",
    "velocity_deriv_method",
    "outlier_removal",
    "total_dropped_frames",
    "os_name",
    "os_version",
    "os_release",
    "architecture",
    "hostname",
    "os_user",
    "cpu_name",
    "cpu_cores_logical",
    "cpu_cores_physical",
    "total_ram_gb",
    "disk_total_gb",
    "disk_free_gb",
    "gpu_info",
    "app_version",
    "available_extensions_json",
    "raw_json",
    # GDPR-09. Added by migration 6, which is what brings an established
    # database into line -- a column added here alone is VRT-22 again.
    "consent_id",
)


class DatabaseManager:
    """
    Relational SQLite manager for persisting static metadata structures
    (Subject Profiles, Hardware Configurations, Calibration Data, Processing Metadata)
    linked to the high-frequency Parquet time-series datasets via session UUIDs.
    """

    def __init__(self, db_path: str | Path | None = None):
        # Resolved at call time, not as a default argument: a default is
        # evaluated once at import and would freeze the path before any
        # configuration could be read. See src/config/settings.py (VRT-6).
        self.db_path = Path(db_path) if db_path else get_settings().paths.metadata_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._repo = SessionRepository(self.db_path)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Delegate to the migration runner (VRT-11).

        This method used to be 167 lines: one CREATE TABLE followed by fourteen
        ALTER TABLE calls, each wrapped in ``except sqlite3.OperationalError:
        pass``. That idiom cannot tell "already applied" from "failed", which is
        how the column behind VRT-22 went missing for days without an error.

        It also meant two things owned this schema once SessionRepository
        arrived, both writing the same file. Now there is one owner: the
        numbered, recorded migrations in
        ``src.infrastructure.persistence.migrations``.
        """
        migrate(self.db_path, baseline_schema=SessionRepository._create_baseline)

    def list_all_sessions(self) -> list:
        """Every session this machine knows about. Delegates to the repository."""
        return self._repo.list_all()

    def get_sessions_for_patient(self, patient_id: str) -> list:
        """Sessions linked to one patient. Delegates to the repository."""
        return self._repo.list_for_patient(patient_id)

    def persist_experiment(self, metadata: dict[str, Any]) -> bool:
        """
        Extracts nested category dicts from the static context definition and
        flattens them into the relational ledger for long-term tracking.

        Returns:
            Whether the row was written. Annotated ``-> None`` until VRT-14,
            although the body has always returned True or False and the engine
            has always branched on it -- ``src.storage.database_manager`` is in
            mypy's ignore list (VRT-11), so nothing checked. Declaring
            :class:`~src.application.ports.SessionMetadataSink` is what surfaced
            it: a port is a claim about a type, and the checker compares the
            implementation against it whether or not the module is exempt.
        """
        static_meta = metadata.get("M-IV_Static_Metadata", {})
        calib_meta = metadata.get("C-V_Calibration", {})
        subj_labels = metadata.get("Q-VI_Subjective_Labels", {})
        hw_meta = metadata.get("H-VII_Hardware_Capabilities", {})
        proc_meta = metadata.get("P-VIII_Processing_Metadata", {})
        sys_profile = metadata.get("S-IX_System_Profile", {})

        session_id = static_meta.get("session_id", "UNKNOWN")

        placeholders = ", ".join("?" * len(SESSION_METADATA_COLUMNS))
        query = (
            f"INSERT INTO session_metadata ({', '.join(SESSION_METADATA_COLUMNS)}) "
            f"VALUES ({placeholders})"
        )

        values = (
            session_id,
            static_meta.get("patient_id"),
            static_meta.get("start_timestamp_utc", "Unknown"),
            static_meta.get("subject_id", "UNKNOWN"),
            static_meta.get("subject_age", 0),
            static_meta.get("subject_biological_sex", "Unknown"),
            static_meta.get("subject_height_cm", 0.0),
            static_meta.get("subject_weight_kg", 0.0),
            static_meta.get("subject_vr_exp", "Unknown"),
            static_meta.get("subject_ipd_mm", 0.0),
            static_meta.get("vision_correction", "None"),
            static_meta.get("vision_impairment", "None"),
            static_meta.get("tracking_space_type", "Unknown"),
            static_meta.get("play_area_width_m", 0.0),
            static_meta.get("play_area_length_m", 0.0),
            static_meta.get("host_os_version", "Unknown"),
            static_meta.get("host_cpu_model", "Unknown"),
            static_meta.get("host_gpu_model", "Unknown"),
            static_meta.get("host_ram_gb", 0.0),
            static_meta.get("gpu_driver_version", "Unknown"),
            hw_meta.get("openxr_runtime", "Unknown"),
            hw_meta.get("hmd_model", "Unknown"),
            static_meta.get("hmd_firmware", "Unknown"),
            static_meta.get("hmd_refresh_rate", 0.0),
            static_meta.get("hmd_render_res_w", 0),
            static_meta.get("hmd_render_res_h", 0),
            static_meta.get("hmd_fov_horizontal", 0.0),
            static_meta.get("hmd_fov_vertical", 0.0),
            static_meta.get("tracking_system", "Unknown"),
            static_meta.get("controller_model", "Unknown"),
            hw_meta.get("has_eye_tracking", 0),
            hw_meta.get("has_face_tracking", 0),
            hw_meta.get("has_body_tracking", 0),
            calib_meta.get("neutral_head_height", 0.0),
            calib_meta.get("shoulder_width_est", 0.0),
            calib_meta.get("arm_length_left", 0.0),
            calib_meta.get("arm_length_right", 0.0),
            calib_meta.get("dominant_hand", "Right"),
            subj_labels.get("ssq_nausea_score", 0.0),
            subj_labels.get("ssq_oculomotor_score", 0.0),
            subj_labels.get("ssq_disorientation", 0.0),
            subj_labels.get("nasa_tlx_mental", 0.0),
            subj_labels.get("nasa_tlx_physical", 0.0),
            subj_labels.get("nasa_tlx_frustration", 0.0),
            subj_labels.get("perceived_temp_c", 22.0),
            subj_labels.get("session_rating", 0),
            proc_meta.get("preprocessor_version", "Unknown"),
            proc_meta.get("smoothing_algorithm", "None"),
            proc_meta.get("scaling_method", "None"),
            proc_meta.get("velocity_deriv_method", "None"),
            proc_meta.get("outlier_removal", "None"),
            proc_meta.get("total_dropped_frames", 0),
            sys_profile.get("os_name", "Unknown"),
            sys_profile.get("os_version", "Unknown"),
            sys_profile.get("os_release", "Unknown"),
            sys_profile.get("architecture", "Unknown"),
            sys_profile.get("hostname", "Unknown"),
            sys_profile.get("os_user", "Unknown"),
            sys_profile.get("cpu_name", "Unknown"),
            sys_profile.get("cpu_cores_logical", 0),
            sys_profile.get("cpu_cores_physical", 0),
            sys_profile.get("total_ram_gb", 0.0),
            sys_profile.get("disk_total_gb", 0.0),
            sys_profile.get("disk_free_gb", 0.0),
            sys_profile.get("gpu_info", "Unknown"),
            "1.0.0",
            json.dumps(hw_meta.get("available_extensions", [])),
            json.dumps(metadata),
            static_meta.get("consent_id"),
        )

        if len(values) != len(SESSION_METADATA_COLUMNS):
            # A mismatch here is a programming error, not a runtime condition:
            # someone added a column to one list and not the other. Raise rather
            # than let sqlite report it as a message that the caller logs and
            # ignores -- that is precisely how the original defect survived.
            raise ValueError(
                f"session_metadata INSERT builds {len(SESSION_METADATA_COLUMNS)} columns "
                f"but {len(values)} values were supplied; the two lists have drifted."
            )

        try:
            with transaction(self.db_path) as conn:
                conn.execute(query, values)
            # The ALTER TABLE that used to sit inside this write is gone: adding
            # a column on every INSERT was schema management smuggled into a data
            # path, and it is what let a missing column go unnoticed. Migration 2
            # owns that column now (VRT-11).
            logger.info(f"Static experiment metadata committed for session: {session_id}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Session {session_id} already exists in relational ledger.")
            return False
        except sqlite3.Error as e:
            logger.error(f"Failed to persist static metadata for session {session_id}: {e}")
            return False

    # Fixed, whitelisted set of columns the post-session questionnaire is
    # allowed to write. Deliberately not a free-form dict->SQL builder off
    # user input — this whitelist is the only thing standing between the
    # /api/sessions/{id}/questionnaire endpoint and an arbitrary column write.
    QUESTIONNAIRE_FIELDS = (
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
    )

    def save_subjective_questionnaire(self, session_id: str, fields: dict[str, Any]) -> bool:
        """Persist a scored questionnaire. Delegates to the repository."""
        return self._repo.save_questionnaire(session_id, fields)

    def get_session_row(self, session_id: str) -> dict[str, Any]:
        """Full flat session row. Delegates to the repository."""
        return self._repo.get(session_id)
