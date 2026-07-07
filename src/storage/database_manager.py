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
    (Subject Profiles, Hardware Configurations, Calibration Data) linked 
    to the high-frequency Parquet time-series datasets via session UUIDs.
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
        """Constructs tables matching Requirement Categories 4, 5, and 6."""
        query = """
        CREATE TABLE IF NOT EXISTS session_metadata (
            session_id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL,
            subject_age INTEGER,
            subject_biological_sex TEXT,
            subject_height_cm REAL,
            subject_weight_kg REAL,
            subject_vr_exp TEXT,
            subject_ipd_mm REAL,
            
            dominant_hand TEXT,
            
            ssq_nausea_score REAL,
            ssq_oculomotor_score REAL,
            nasa_tlx_mental REAL,
            nasa_tlx_physical REAL,
            session_rating INTEGER,
            
            openxr_runtime TEXT,
            hmd_model TEXT,
            has_eye_tracking INTEGER,
            has_face_tracking INTEGER,
            has_body_tracking INTEGER,
            
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            with self._get_connection() as conn:
                conn.execute(query)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"SQLite Schema Initialization Failed: {e}")

    def persist_experiment(self, metadata: Dict[str, Any]) -> None:
        """
        Extracts nested category dicts from the static context definition and
        flattens them into the relational ledger for long-term tracking.
        """
        static_meta = metadata.get("M-IV_Static_Metadata", {})
        calib_meta = metadata.get("C-V_Calibration", {})
        subj_labels = metadata.get("Q-VI_Subjective_Labels", {})
        hw_meta = metadata.get("H-VII_Hardware_Capabilities", {})

        session_id = static_meta.get("session_id", "UNKNOWN")

        query = """
        INSERT INTO session_metadata (
            session_id, subject_id, subject_age, subject_biological_sex,
            subject_height_cm, subject_weight_kg, subject_vr_exp, subject_ipd_mm,
            dominant_hand,
            ssq_nausea_score, ssq_oculomotor_score, nasa_tlx_mental, nasa_tlx_physical, session_rating,
            openxr_runtime, hmd_model, has_eye_tracking, has_face_tracking, has_body_tracking,
            raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        values = (
            session_id,
            static_meta.get("subject_id", "UNKNOWN"),
            static_meta.get("subject_age", 0),
            static_meta.get("subject_biological_sex", "Unknown"),
            static_meta.get("subject_height_cm", 0.0),
            static_meta.get("subject_weight_kg", 0.0),
            static_meta.get("subject_vr_exp", "Unknown"),
            static_meta.get("subject_ipd_mm", 0.0),
            
            calib_meta.get("dominant_hand", "Right"),
            
            subj_labels.get("ssq_nausea_score", 0.0),
            subj_labels.get("ssq_oculomotor_score", 0.0),
            subj_labels.get("nasa_tlx_mental", 0.0),
            subj_labels.get("nasa_tlx_physical", 0.0),
            subj_labels.get("session_rating", 0),
            
            hw_meta.get("openxr_runtime", "Unknown"),
            hw_meta.get("hmd_model", "Unknown"),
            hw_meta.get("has_eye_tracking", 0),
            hw_meta.get("has_face_tracking", 0),
            hw_meta.get("has_body_tracking", 0),
            
            json.dumps(metadata)
        )

        try:
            with self._get_connection() as conn:
                conn.execute(query, values)
                conn.commit()
            logger.info(f"Static experiment metadata committed for session: {session_id}")
        except sqlite3.IntegrityError:
            logger.warning(f"Session {session_id} already exists in relational ledger.")
        except sqlite3.Error as e:
            logger.error(f"Failed to persist static metadata: {e}")