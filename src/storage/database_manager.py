# src/storage/database_manager.py

import sqlite3
import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Relational SQLite manager for persisting static metadata structures 
    (Subject Profiles, Hardware Configurations, Calibration Data, Processing Metadata) 
    linked to the high-frequency Parquet time-series datasets via session UUIDs.
    """

    def __init__(self, db_path: str = "Sessions/vr_metadata.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        """Constructs tables matching Requirement Categories 4, 5, 6, and 8."""
        query = """
        CREATE TABLE IF NOT EXISTS session_metadata (
            session_id TEXT PRIMARY KEY,
            start_timestamp_utc TEXT,
            subject_id TEXT NOT NULL,
            subject_age INTEGER,
            subject_biological_sex TEXT,
            subject_height_cm REAL,
            subject_weight_kg REAL,
            subject_vr_exp TEXT,
            subject_ipd_mm REAL,
            vision_correction TEXT,
            vision_impairment TEXT,

            tracking_space_type TEXT,
            play_area_width_m REAL,
            play_area_length_m REAL,
            host_os_version TEXT,
            host_cpu_model TEXT,
            host_gpu_model TEXT,
            host_ram_gb REAL,
            gpu_driver_version TEXT,
            openxr_runtime TEXT,
            hmd_model TEXT,
            hmd_firmware TEXT,
            hmd_refresh_rate REAL,
            hmd_render_res_w INTEGER,
            hmd_render_res_h INTEGER,
            hmd_fov_horizontal REAL,
            hmd_fov_vertical REAL,
            tracking_system TEXT,
            controller_model TEXT,
            has_eye_tracking INTEGER,
            has_face_tracking INTEGER,
            has_body_tracking INTEGER,

            neutral_head_height REAL,
            shoulder_width_est REAL,
            arm_length_left REAL,
            arm_length_right REAL,
            dominant_hand TEXT,

            ssq_nausea_score REAL,
            ssq_oculomotor_score REAL,
            ssq_disorientation REAL,
            nasa_tlx_mental REAL,
            nasa_tlx_physical REAL,
            nasa_tlx_frustration REAL,
            perceived_temp_c REAL,
            session_rating INTEGER,

            preprocessor_version TEXT,
            smoothing_algorithm TEXT,
            scaling_method TEXT,
            velocity_deriv_method TEXT,
            outlier_removal TEXT,
            total_dropped_frames INTEGER,

            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            -- System & Environment Profile (Cat 9)
            os_name TEXT,
            os_version TEXT,
            os_release TEXT,
            architecture TEXT,
            hostname TEXT,
            os_user TEXT,
            cpu_name TEXT,
            cpu_cores_logical INTEGER,
            cpu_cores_physical INTEGER,
            total_ram_gb REAL,
            disk_total_gb REAL,
            disk_free_gb REAL,
            gpu_info TEXT,
            app_version TEXT
        );
        """
        try:
            with self._get_connection() as conn:
                conn.execute(query)
                conn.commit()
            logger.info("SQLite Schema Initialization Successful with full specification mapping.")
        except sqlite3.Error as e:
            # This used to be swallowed — every persist_experiment() call afterward would fail
            # silently against a table that never got created. Fail loudly instead.
            logger.critical(f"SQLite Schema Initialization FAILED — session metadata cannot be persisted: {e}")
            raise

    def persist_experiment(self, metadata: Dict[str, Any]) -> None:
        """
        Extracts nested category dicts from the static context definition and
        flattens them into the relational ledger for long-term tracking.
        """
        static_meta = metadata.get("M-IV_Static_Metadata", {})
        calib_meta = metadata.get("C-V_Calibration", {})
        subj_labels = metadata.get("Q-VI_Subjective_Labels", {})
        hw_meta = metadata.get("H-VII_Hardware_Capabilities", {})
        proc_meta = metadata.get("P-VIII_Processing_Metadata", {})
        sys_profile = metadata.get("S-IX_System_Profile", {})
        
        session_id = static_meta.get("session_id", "UNKNOWN")

        query = """
        INSERT INTO session_metadata (
            session_id, start_timestamp_utc, subject_id, subject_age, subject_biological_sex,
            subject_height_cm, subject_weight_kg, subject_vr_exp, subject_ipd_mm,
            vision_correction, vision_impairment,
            
            tracking_space_type, play_area_width_m, play_area_length_m, host_os_version,
            host_cpu_model, host_gpu_model, host_ram_gb, gpu_driver_version,
            openxr_runtime, hmd_model, hmd_firmware, hmd_refresh_rate,
            hmd_render_res_w, hmd_render_res_h, hmd_fov_horizontal, hmd_fov_vertical,
            tracking_system, controller_model, has_eye_tracking, has_face_tracking, has_body_tracking,
            
            neutral_head_height, shoulder_width_est, arm_length_left, arm_length_right, dominant_hand,
            
            ssq_nausea_score, ssq_oculomotor_score, ssq_disorientation,
            nasa_tlx_mental, nasa_tlx_physical, nasa_tlx_frustration,
            perceived_temp_c, session_rating,
            
            preprocessor_version, smoothing_algorithm, scaling_method,
            velocity_deriv_method, outlier_removal, total_dropped_frames,
            
            os_name, os_version, os_release, architecture, hostname, os_user,
            cpu_name, cpu_cores_logical, cpu_cores_physical, total_ram_gb,
            disk_total_gb, disk_free_gb, gpu_info, app_version, available_extensions_json,
            
            raw_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?
        )
        """

        values = (
            session_id,
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
            
            json.dumps(metadata)
        )

        try:
            with self._get_connection() as conn:
                conn.execute(query, values)
                conn.commit()
            logger.info(f"Static experiment metadata committed for session: {session_id}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Session {session_id} already exists in relational ledger.")
            return False
        except sqlite3.Error as e:
            logger.error(f"Failed to persist static metadata for session {session_id}: {e}")
            return False