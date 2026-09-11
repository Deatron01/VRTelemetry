# src/interfaces/api/schemas/patients.py
"""Patient create and update models."""

from __future__ import annotations

from pydantic import BaseModel, StrictBool

from src.application.consent import ConsentSubmission, WithdrawalScope


class ConsentSubmissionModel(BaseModel):
    """The participant's answers from the consent screen (GDPR-09).

    ``displayed_sha256`` carries the hash of every text the screen displayed,
    as served by ``GET /api/consent/texts``; the server refuses a consent whose
    hashes do not match the current wording. Booleans are strict: ``"yes"`` or
    ``1`` is not an unambiguous affirmative act, ``true`` is.
    """

    text_version: str
    choices: dict[str, StrictBool]
    displayed_sha256: dict[str, str]
    researcher_confirmations: dict[str, StrictBool]
    language: str = "en"

    def to_domain(self) -> ConsentSubmission:
        return ConsentSubmission(
            text_version=self.text_version,
            choices=dict(self.choices),
            displayed_sha256=dict(self.displayed_sha256),
            researcher_confirmations=dict(self.researcher_confirmations),
            language=self.language,
        )


class PatientCreateRequest(BaseModel):
    """A new participant, and the consent they gave on screen.

    ``gdpr_consent_given`` -- a boolean the researcher ticked -- is gone
    (GDPR-09). A request without ``consent`` is refused with 403.
    """

    display_name: str
    consent: ConsentSubmissionModel | None = None
    external_ref: str = ""
    date_of_birth: str = ""
    biological_sex: str = ""
    notes: str = ""
    # Self-reported health/demographic profile — see PatientManager.HEALTH_PROFILE_FIELDS.
    # Collected once here rather than re-asked on every recording session; the values
    # get snapshotted into each session's own metadata row at recording time.
    age_years: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    dominant_hand: str = ""
    vr_experience_level: str = ""
    vr_experience_hours_estimate: float | None = None
    gaming_experience_hours_per_week: float | None = None
    vision_correction: str = ""
    vision_impairment: str = ""
    motion_sickness_susceptibility: str = ""
    relevant_health_conditions: str = ""


class PatientUpdateRequest(BaseModel):
    display_name: str | None = None
    external_ref: str | None = None
    date_of_birth: str | None = None
    biological_sex: str | None = None
    notes: str | None = None
    age_years: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    dominant_hand: str | None = None
    vr_experience_level: str | None = None
    vr_experience_hours_estimate: float | None = None
    gaming_experience_hours_per_week: float | None = None
    vision_correction: str | None = None
    vision_impairment: str | None = None
    motion_sickness_susceptibility: str | None = None
    relevant_health_conditions: str | None = None


class WithdrawalRequest(BaseModel):
    """What the participant chose on the withdrawal dialog.

    Defaults to ``FUTURE_ONLY`` -- stop recording, keep what exists -- because
    that is what an empty ``POST .../withdraw-consent`` has always meant.
    """

    scope: WithdrawalScope = WithdrawalScope.FUTURE_ONLY
