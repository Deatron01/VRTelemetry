# src/interfaces/api/schemas/recording.py
"""Recording start and live experiment state models."""

from __future__ import annotations

from pydantic import BaseModel


class SessionStartConfig(BaseModel):
    patient_id: str
    subject_id: str = "SUB_UNKN_01"
    backend: str = "auto"
    port: int = 5005
    #: The consent this recording is made under (GDPR-09). None means the
    #: participant's current consent for the configured study. The old
    #: ``gdpr_consent: bool`` -- a box the researcher ticked -- is gone; the
    #: participant's recorded consent is what authorises a recording now.
    consent_id: str | None = None
    output_dir: str | None = None
    # None means "use the configured hub"; the placeholder address this
    # used to default to shipped as a live value (VRT-6).
    central_server_url: str | None = None
    # Anthropometric calibration overrides (centimeters) — optional. When omitted,
    # _default_anthropometrics() derives a documented height-based estimate from
    # the patient's profile instead of silently persisting 0.0 like every session
    # recorded before this existed did.
    arm_length_left_cm: float | None = None
    arm_length_right_cm: float | None = None
    neutral_head_height_cm: float | None = None
    shoulder_width_cm: float | None = None


class SceneUpdate(BaseModel):
    scene_id: float


class EventMarkerUpdate(BaseModel):
    value: float = 1.0


class HapticTrigger(BaseModel):
    side: str
    intensity: float
    duration_sec: float = 0.1


class TargetPosition(BaseModel):
    x: float
    y: float
    z: float
