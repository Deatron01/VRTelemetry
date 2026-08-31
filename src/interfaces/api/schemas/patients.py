# src/interfaces/api/schemas/patients.py
"""Patient create and update models."""

from __future__ import annotations

from pydantic import BaseModel


class PatientCreateRequest(BaseModel):
    display_name: str
    gdpr_consent_given: bool
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
