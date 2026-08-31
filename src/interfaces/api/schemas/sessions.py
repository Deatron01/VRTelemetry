# src/interfaces/api/schemas/sessions.py
"""Session update model."""

from __future__ import annotations

from pydantic import BaseModel


class SessionUpdate(BaseModel):
    subject_id: str | None = None
    start_timestamp_utc: str | None = None
    subject_vr_exp: str | None = None
    session_rating: int | None = None
    # Anthropometric/calibration fields — editable after the fact (meters/mm,
    # matching how they're stored — see _default_anthropometrics for the
    # centimeter<->meter conversion done at recording-start time).
    subject_ipd_mm: float | None = None
    neutral_head_height: float | None = None
    shoulder_width_est: float | None = None
    arm_length_left: float | None = None
    arm_length_right: float | None = None
    dominant_hand: str | None = None
