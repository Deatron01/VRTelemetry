# src/patients/patient_manager.py

import sqlite3
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from src.core.exceptions import GDPRConsentError

logger = logging.getLogger(__name__)

CURRENT_CONSENT_VERSION = "1.0"


class PatientManager:
    """
    CRUD authority for patient/subject records, kept separate from raw telemetry
    (Parquet) and per-run session metadata (DatabaseManager.session_metadata). A
    patient record is the durable identity a researcher re-selects across many
    recording sessions; session_metadata rows reference patients.patient_id.

    GDPR posture:
      - A patient CANNOT be created without explicit, timestamped consent
        (gdpr_consent_given=True). This mirrors the GDPRConsentError already
        enforced for live biometric acquisition (src.core.exceptions), extended
        to cover at-rest storage of the subject's identifying/demographic profile.
      - Consent can be withdrawn independently of deletion (Art. 7(3) — as easy
        to withdraw as to give). Withdrawing blocks starting new sessions against
        this patient but does not delete existing recordings.
      - delete_patient() implements a right-to-erasure request: identifying
        fields are anonymized in place (not hard-deleted) so historical
        session_metadata rows referencing this patient_id keep referential
        integrity. Pass hard_delete=True to fully remove the row when nothing
        references it.
    """

    def __init__(self, db_path: str = "Sessions/patients.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        query = """
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            external_ref TEXT,
            date_of_birth TEXT,
            biological_sex TEXT,
            notes TEXT,

            gdpr_consent_given INTEGER NOT NULL DEFAULT 0,
            gdpr_consent_version TEXT,
            gdpr_consent_timestamp TEXT,
            gdpr_consent_withdrawn_at TEXT,

            is_anonymized INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            with self._get_connection() as conn:
                conn.execute(query)
                conn.commit()
            logger.info("Patient registry schema initialized.")
        except sqlite3.Error as e:
            logger.critical(f"Failed to initialize patient registry schema: {e}")
            raise

    # ---------------------------------------------------------------- create

    def create_patient(
        self,
        display_name: str,
        gdpr_consent_given: bool,
        external_ref: str = "",
        date_of_birth: str = "",
        biological_sex: str = "",
        notes: str = "",
        gdpr_consent_version: str = CURRENT_CONSENT_VERSION,
    ) -> Dict[str, Any]:
        if not display_name or not display_name.strip():
            raise ValueError("display_name is required")

        if not gdpr_consent_given:
            raise GDPRConsentError(
                "CRITICAL: Cannot create a patient record without explicit, "
                "logged GDPR consent for storage/processing of subject data."
            )

        patient_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            conn.execute(
                """INSERT INTO patients (
                    patient_id, display_name, external_ref, date_of_birth,
                    biological_sex, notes, gdpr_consent_given, gdpr_consent_version,
                    gdpr_consent_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (patient_id, display_name.strip(), external_ref, date_of_birth,
                 biological_sex, notes, gdpr_consent_version, now)
            )
            conn.commit()

        logger.info(f"Patient record created: {patient_id} (consent v{gdpr_consent_version} @ {now})")
        return self.get_patient(patient_id)

    # ---------------------------------------------------------------- read

    def list_patients(self, include_anonymized: bool = False) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if include_anonymized:
                rows = conn.execute("SELECT * FROM patients ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM patients WHERE is_anonymized = 0 ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
            return dict(row) if row else None

    # ---------------------------------------------------------------- update

    def update_patient(self, patient_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        existing = self.get_patient(patient_id)
        if not existing:
            return None
        if existing["is_anonymized"]:
            raise ValueError("Cannot edit an anonymized (erased) patient record.")

        editable_fields = {"display_name", "external_ref", "date_of_birth", "biological_sex", "notes"}
        set_fields = {k: v for k, v in updates.items() if k in editable_fields}
        if not set_fields:
            return existing

        set_fields["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in set_fields)
        values = list(set_fields.values()) + [patient_id]

        with self._get_connection() as conn:
            conn.execute(f"UPDATE patients SET {set_clause} WHERE patient_id = ?", values)
            conn.commit()

        return self.get_patient(patient_id)

    def withdraw_consent(self, patient_id: str) -> Optional[Dict[str, Any]]:
        """GDPR Art. 7(3): consent must be as easy to withdraw as to give."""
        existing = self.get_patient(patient_id)
        if not existing:
            return None
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE patients SET gdpr_consent_given = 0, gdpr_consent_withdrawn_at = ?, updated_at = ? WHERE patient_id = ?",
                (now, now, patient_id)
            )
            conn.commit()
        logger.warning(f"GDPR consent withdrawn for patient {patient_id} at {now}")
        return self.get_patient(patient_id)

    # ---------------------------------------------------------------- delete / erasure

    def delete_patient(self, patient_id: str, hard_delete: bool = False) -> bool:
        """
        Default behavior fulfills a right-to-erasure request by scrubbing
        identifying fields in place (soft erasure) so historical session_metadata
        rows referencing this patient_id don't dangle. hard_delete=True instead
        removes the row entirely — only safe when the caller has confirmed no
        sessions reference this patient.
        """
        existing = self.get_patient(patient_id)
        if not existing:
            return False

        with self._get_connection() as conn:
            if hard_delete:
                conn.execute("DELETE FROM patients WHERE patient_id = ?", (patient_id,))
            else:
                now = datetime.utcnow().isoformat()
                conn.execute(
                    """UPDATE patients SET
                        display_name = '[ERASED]', external_ref = '', date_of_birth = '',
                        biological_sex = '', notes = '', is_anonymized = 1,
                        gdpr_consent_given = 0, updated_at = ?
                       WHERE patient_id = ?""",
                    (now, patient_id)
                )
            conn.commit()

        logger.warning(f"Patient {patient_id} erased ({'hard delete' if hard_delete else 'anonymized in place'}).")
        return True