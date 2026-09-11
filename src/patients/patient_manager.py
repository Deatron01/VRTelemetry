# src/patients/patient_manager.py

import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.core.exceptions import GDPRConsentError
from src.domain.hub_projection import age_from_date_of_birth
from src.patients.consent_texts import CONSENT_TEXT_VERSION
from src.utils.clock import utc_now_iso, utc_today

logger = logging.getLogger(__name__)

#: The consent wording version a new record is stamped with. Kept in step with
#: the wording itself, which lives in src/patients/consent_texts.py (GDPR-09).
CURRENT_CONSENT_VERSION = CONSENT_TEXT_VERSION


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
      - The ``gdpr_consent_*`` columns are a *summary*. The evidence -- the
        participant's own choices, the exact wording, who supervised -- is the
        consent register (GDPR-09): see src/application/consent.py, which is
        the only route by which the HTTP API creates a patient.
      - Consent can be withdrawn independently of deletion (Art. 7(3) — as easy
        to withdraw as to give). Withdrawing blocks starting new sessions against
        this patient but does not delete existing recordings.
      - delete_patient() handles *this row only*: identifying fields are
        anonymized in place, or the row removed with hard_delete=True. It is
        not the right to erasure by itself -- recordings, session rows and hub
        copies are other stores. src/application/erasure.py (GDPR-10) is the
        right to erasure; it deletes those first and calls this last.
    """

    def __init__(self, db_path: str | Path | None = None):
        # Resolved at call time, not as a default argument: a default is
        # evaluated once at import and would freeze the path before any
        # configuration could be read. See src/config/settings.py (VRT-6).
        self.db_path = Path(db_path) if db_path else get_settings().paths.patients_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # Self-reported columns added so per-session telemetry/biometric measures
    # (SSQ scores, NASA-TLX, frame data — see DatabaseManager.session_metadata)
    # can be statistically joined against real subject covariates instead of
    # the "Unknown"/0.0 placeholders that column set has always defaulted to.
    # Collected once per patient rather than re-asked every session; snapshotted
    # into each session's own row at recording time (see main.py start_recording)
    # so editing a patient's profile later never silently rewrites past sessions'
    # recorded covariates.
    HEALTH_PROFILE_FIELDS = (
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

    def _initialize_schema(self) -> None:
        query = """
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            external_ref TEXT,
            date_of_birth TEXT,
            biological_sex TEXT,
            notes TEXT,

            -- Self-reported health / demographic profile (see HEALTH_PROFILE_FIELDS)
            age_years INTEGER,                        -- fallback when date_of_birth isn't provided
            height_cm REAL,
            weight_kg REAL,
            dominant_hand TEXT,                       -- left | right | ambidextrous
            vr_experience_level TEXT,                  -- none | novice | intermediate | experienced | expert
            vr_experience_hours_estimate REAL,
            gaming_experience_hours_per_week REAL,
            vision_correction TEXT,                    -- none | glasses | contacts
            vision_impairment TEXT,                     -- free text, e.g. "colorblind", "astigmatism"
            motion_sickness_susceptibility TEXT,        -- none | mild | moderate | severe
            relevant_health_conditions TEXT,            -- free text (vestibular, cardiac, epilepsy, etc.)

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

                # Idempotent migrations for DBs created before the health profile
                # columns existed. One ALTER per column, each independently safe
                # to fail with "duplicate column" on a DB that already has it.
                for column in self.HEALTH_PROFILE_FIELDS:
                    col_type = (
                        "REAL"
                        if column
                        in (
                            "height_cm",
                            "weight_kg",
                            "vr_experience_hours_estimate",
                            "gaming_experience_hours_per_week",
                        )
                        else ("INTEGER" if column == "age_years" else "TEXT")
                    )
                    try:
                        conn.execute(f"ALTER TABLE patients ADD COLUMN {column} {col_type}")
                        conn.commit()
                    except sqlite3.OperationalError:
                        pass
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
        age_years: int | None = None,
        height_cm: float | None = None,
        weight_kg: float | None = None,
        dominant_hand: str = "",
        vr_experience_level: str = "",
        vr_experience_hours_estimate: float | None = None,
        gaming_experience_hours_per_week: float | None = None,
        vision_correction: str = "",
        vision_impairment: str = "",
        motion_sickness_susceptibility: str = "",
        relevant_health_conditions: str = "",
    ) -> dict[str, Any]:
        if not display_name or not display_name.strip():
            raise ValueError("display_name is required")

        if not gdpr_consent_given:
            raise GDPRConsentError(
                "CRITICAL: Cannot create a patient record without explicit, "
                "logged GDPR consent for storage/processing of subject data."
            )

        patient_id = str(uuid.uuid4())
        now = utc_now_iso()

        with self._get_connection() as conn:
            conn.execute(
                """INSERT INTO patients (
                    patient_id, display_name, external_ref, date_of_birth,
                    biological_sex, notes,
                    age_years, height_cm, weight_kg, dominant_hand,
                    vr_experience_level, vr_experience_hours_estimate,
                    gaming_experience_hours_per_week, vision_correction,
                    vision_impairment, motion_sickness_susceptibility,
                    relevant_health_conditions,
                    gdpr_consent_given, gdpr_consent_version, gdpr_consent_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    patient_id,
                    display_name.strip(),
                    external_ref,
                    date_of_birth,
                    biological_sex,
                    notes,
                    age_years,
                    height_cm,
                    weight_kg,
                    dominant_hand,
                    vr_experience_level,
                    vr_experience_hours_estimate,
                    gaming_experience_hours_per_week,
                    vision_correction,
                    vision_impairment,
                    motion_sickness_susceptibility,
                    relevant_health_conditions,
                    gdpr_consent_version,
                    now,
                ),
            )
            conn.commit()

        logger.info(
            f"Patient record created: {patient_id} (consent v{gdpr_consent_version} @ {now})"
        )
        return self.get_patient(patient_id)

    # ---------------------------------------------------------------- read

    def list_patients(self, include_anonymized: bool = False) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            if include_anonymized:
                rows = conn.execute("SELECT * FROM patients ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM patients WHERE is_anonymized = 0 ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_patient(self, patient_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
            ).fetchone()
            return dict(row) if row else None

    # ---------------------------------------------------------------- update

    def update_patient(self, patient_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_patient(patient_id)
        if not existing:
            return None
        if existing["is_anonymized"]:
            raise ValueError("Cannot edit an anonymized (erased) patient record.")

        editable_fields = {
            "display_name",
            "external_ref",
            "date_of_birth",
            "biological_sex",
            "notes",
        } | set(self.HEALTH_PROFILE_FIELDS)
        set_fields = {k: v for k, v in updates.items() if k in editable_fields}
        if not set_fields:
            return existing

        set_fields["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in set_fields)
        values = list(set_fields.values()) + [patient_id]

        with self._get_connection() as conn:
            conn.execute(f"UPDATE patients SET {set_clause} WHERE patient_id = ?", values)
            conn.commit()

        return self.get_patient(patient_id)

    def mark_consent_given(
        self, patient_id: str, version: str, given_at_utc: str
    ) -> dict[str, Any] | None:
        """Reflect a newly recorded consent on the patient row.

        The consent register (``consent_records``) is the evidence; these
        columns are a summary of it, kept so the patient list and the hub can
        show a consent state without reading the register. A re-consent after a
        withdrawal clears ``gdpr_consent_withdrawn_at``.
        """
        existing = self.get_patient(patient_id)
        if not existing:
            return None
        if existing["is_anonymized"]:
            raise ValueError("Cannot record consent for an erased patient record.")
        with self._get_connection() as conn:
            conn.execute(
                """UPDATE patients SET gdpr_consent_given = 1, gdpr_consent_version = ?,
                       gdpr_consent_timestamp = ?, gdpr_consent_withdrawn_at = NULL,
                       updated_at = ?
                   WHERE patient_id = ?""",
                (version, given_at_utc, utc_now_iso(), patient_id),
            )
            conn.commit()
        return self.get_patient(patient_id)

    def withdraw_consent(self, patient_id: str) -> dict[str, Any] | None:
        """GDPR Art. 7(3): consent must be as easy to withdraw as to give."""
        existing = self.get_patient(patient_id)
        if not existing:
            return None
        now = utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE patients SET gdpr_consent_given = 0, gdpr_consent_withdrawn_at = ?, updated_at = ? WHERE patient_id = ?",
                (now, now, patient_id),
            )
            conn.commit()
        logger.warning(f"GDPR consent withdrawn for patient {patient_id} at {now}")
        return self.get_patient(patient_id)

    # ---------------------------------------------------------------- delete / erasure

    def estimate_age_years(self, patient: dict[str, Any]) -> int | None:
        """
        Effective age for a session's static metadata: derived from date_of_birth
        when available (most accurate, and stays correct as time passes without
        the researcher re-entering it), falling back to the self-reported
        age_years field for protocols that intentionally collect only age
        (not full DOB) for anonymity, or simply haven't recorded a DOB.
        """
        # One implementation, shared with the hub projection (GDPR-11), which
        # derives the same covariate so the date of birth itself never leaves
        # the workstation.
        derived = age_from_date_of_birth(patient.get("date_of_birth"), utc_today())
        if derived is not None:
            return derived
        age_years = patient.get("age_years")
        return int(age_years) if age_years is not None else None

    def delete_patient(self, patient_id: str, hard_delete: bool = False) -> bool:
        """
        Scrubs identifying and health fields in place (soft erasure), leaving a
        tombstone with the pseudonymous id; hard_delete=True removes the row.

        Only one step of an erasure. Call it through
        :class:`src.application.erasure.ErasureService`, which deletes the
        participant's recordings, session rows and hub copies first -- which is
        also what makes hard_delete safe: nothing references the row any more.
        """
        existing = self.get_patient(patient_id)
        if not existing:
            return False

        with self._get_connection() as conn:
            if hard_delete:
                conn.execute("DELETE FROM patients WHERE patient_id = ?", (patient_id,))
            else:
                now = utc_now_iso()
                # Right-to-erasure scrubs the health/demographic profile too — these
                # are special-category data under the same consent umbrella as the
                # identifying fields, so an erasure request has to clear all of it,
                # not just name/DOB/notes.
                health_reset_clause = ", ".join(
                    f"{col} = NULL" for col in self.HEALTH_PROFILE_FIELDS
                )
                conn.execute(
                    f"""UPDATE patients SET
                        display_name = '[ERASED]', external_ref = '', date_of_birth = '',
                        biological_sex = '', notes = '', is_anonymized = 1,
                        gdpr_consent_given = 0, updated_at = ?,
                        {health_reset_clause}
                       WHERE patient_id = ?""",
                    (now, patient_id),
                )
            conn.commit()

        logger.warning(
            f"Patient {patient_id} erased ({'hard delete' if hard_delete else 'anonymized in place'})."
        )
        return True
