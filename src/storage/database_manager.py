import sqlite3
from pathlib import Path
from typing import Dict, Any

class DatabaseManager:
    """
    Manages low-frequency metadata storage configuration parameters within 
    normalized transactional tables.
    """
    def __init__(self, db_path: str = "Sessions/vr_metadata.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._build_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _build_tables(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Subjects (
                    subject_id TEXT PRIMARY KEY, age INTEGER, biological_sex TEXT,
                    height_cm REAL, weight_kg REAL, vr_experience TEXT, dominant_hand TEXT, ipd_mm REAL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Sessions (
                    session_id TEXT PRIMARY KEY, subject_id TEXT, start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    parquet_file_name TEXT, FOREIGN KEY(subject_id) REFERENCES Subjects(subject_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Questionnaires (
                    session_id TEXT PRIMARY KEY, ssq_nausea REAL, ssq_oculomotor REAL,
                    nasa_tlx_mental REAL, nasa_tlx_physical REAL, session_rating INTEGER,
                    FOREIGN KEY(session_id) REFERENCES Sessions(session_id)
                )
            """)
            conn.commit()

    def persist_experiment(self, packet: Dict[str, Any]) -> None:
        static = packet.get("M-IV_Static_Metadata", {})
        calib = packet.get("C-V_Calibration", {})
        labels = packet.get("Q-VI_Subjective_Labels", {})
        
        sid = static.get("session_id")
        sub_id = static.get("subject_id")

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO Subjects (subject_id, age, biological_sex, height_cm, weight_kg, vr_experience, dominant_hand, ipd_mm)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_id) DO UPDATE SET age=excluded.age, ipd_mm=excluded.ipd_mm
            """, (sub_id, static.get("subject_age"), static.get("subject_biological_sex"), static.get("subject_height_cm"), static.get("subject_weight_kg"), static.get("subject_vr_exp"), calib.get("dominant_hand"), calib.get("subject_ipd_mm")))

            cursor.execute("INSERT OR IGNORE INTO Sessions (session_id, subject_id, parquet_file_name) VALUES (?, ?, ?)",
                           (sid, sub_id, f"vr_telemetry_{sid}.parquet"))

            cursor.execute("""
                INSERT OR REPLACE INTO Questionnaires (session_id, ssq_nausea, ssq_oculomotor, nasa_tlx_mental, nasa_tlx_physical, session_rating)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sid, labels.get("ssq_nausea_score"), labels.get("ssq_oculomotor_score"), labels.get("nasa_tlx_mental"), labels.get("nasa_tlx_physical"), labels.get("session_rating")))
            conn.commit()