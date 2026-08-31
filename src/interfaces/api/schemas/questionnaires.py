# src/interfaces/api/schemas/questionnaires.py
"""Post-session subjective questionnaire model."""

from __future__ import annotations

from pydantic import BaseModel


class QuestionnaireSubmission(BaseModel):
    """
    Flat submission model for the post-session subjective questionnaire —
    16 SSQ symptom severities (0-3) and 6 NASA-TLX subscale ratings (0-100).
    All optional so a partially-completed form still submits something
    defensible rather than being all-or-nothing; src.analytics.questionnaires
    treats missing items as 0 and clamps out-of-range values.
    """

    # SSQ items (0-3)
    general_discomfort: int | None = None
    fatigue: int | None = None
    headache: int | None = None
    eye_strain: int | None = None
    difficulty_focusing: int | None = None
    increased_salivation: int | None = None
    sweating: int | None = None
    nausea: int | None = None
    difficulty_concentrating: int | None = None
    fullness_of_head: int | None = None
    blurred_vision: int | None = None
    dizziness_eyes_open: int | None = None
    dizziness_eyes_closed: int | None = None
    vertigo: int | None = None
    stomach_awareness: int | None = None
    burping: int | None = None
    # NASA-TLX items (0-100)
    mental_demand: float | None = None
    physical_demand: float | None = None
    temporal_demand: float | None = None
    performance: float | None = None
    effort: float | None = None
    frustration: float | None = None
    # Thermal comfort + free-form session context
    thermal_comfort: str | None = None
    perceived_temp_c: float | None = None
    session_rating: int | None = None
