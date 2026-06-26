import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

class DatabaseManager:
    """
    Manages the SQLite relational database for low-frequency, static metadata.
    This includes Subject Demographics, Calibration Data, and Subjective Questionnaires.
    """
    def __init__(self, db_path: str = "Sessions/vr_metadata.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        # Check_same_thread=False allows our UI or Engine threads to write safely 
        # (though SQLite locks natively on write).
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        """Creates normalized tables if they do not exist based on the Csocsó experiment requirements."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Subjects Table (Demographics & Biometrics)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Subjects (
                    subject_id TEXT PRIMARY KEY,
                    age INTEGER,
                    biological_sex TEXT,
                    height_cm REAL,
                    weight_kg REAL,
                    vr_experience TEXT,
                    dominant_hand TEXT,
                    ipd_mm REAL
                )
            """)

            # Sessions Table (Links to Parquet files)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Sessions (
                    session_id TEXT PRIMARY KEY,
                    subject_id TEXT,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    parquet_file_name TEXT,
                    FOREIGN KEY(subject_id) REFERENCES Subjects(subject_id)
                )
            """)

            # Questionnaires Table (SSQ, NASA-TLX)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Questionnaires (
                    session_id TEXT PRIMARY KEY,
                    ssq_nausea REAL,
                    ssq_oculomotor REAL,
                    nasa_tlx_mental REAL,
                    nasa_tlx_physical REAL,
                    session_rating INTEGER,
                    FOREIGN KEY(session_id) REFERENCES Sessions(session_id)
                )
            """)
            conn.commit()

    def save_experiment_data(self, metadata: Dict[str, Any]) -> None:
        """
        Parses the nested dictionary from the UI (Experiment Manager) 
        and inserts it into the normalized SQL tables safely.
        """
        static = metadata.get("M-IV_Static_Metadata", {})
        calib = metadata.get("C-V_Calibration", {})
        labels = metadata.get("Q-VI_Subjective_Labels", {})

        subject_id = static.get("subject_id")
        session_id = static.get("session_id")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Upsert Subject (Update if IPD or weight changed between sessions)
            cursor.execute("""
                INSERT INTO Subjects (subject_id, age, biological_sex, height_cm, weight_kg, vr_experience, dominant_hand, ipd_mm)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_id) DO UPDATE SET
                    age=excluded.age, height_cm=excluded.height_cm, weight_kg=excluded.weight_kg, 
                    vr_experience=excluded.vr_experience, ipd_mm=excluded.ipd_mm
            """, (
                subject_id, static.get("subject_age"), static.get("subject_biological_sex"),
                static.get("subject_height_cm"), static.get("subject_weight_kg"),
                static.get("subject_vr_exp"), calib.get("dominant_hand"), calib.get("subject_ipd_mm")
            ))

            # 2. Insert Session
            cursor.execute("""
                INSERT OR IGNORE INTO Sessions (session_id, subject_id, parquet_file_name)
                VALUES (?, ?, ?)
            """, (session_id, subject_id, f"vr_telemetry_{session_id}.parquet"))

            # 3. Insert Questionnaire Labels
            cursor.execute("""
                INSERT OR REPLACE INTO Questionnaires (session_id, ssq_nausea, ssq_oculomotor, nasa_tlx_mental, nasa_tlx_physical, session_rating)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                session_id, labels.get("ssq_nausea_score"), labels.get("ssq_oculomotor_score"),
                labels.get("nasa_tlx_mental"), labels.get("nasa_tlx_physical"), labels.get("session_rating")
            ))
            
            conn.commit()