# src/domain/session_profile.py
"""Subject profile and anthropometric baselines for a recording (VRT-10).

Moved out of src/main.py, where these sat between route handlers. They take a
plain metadata dict rather than a TelemetryEngine, which is what makes them
testable without constructing an engine -- see tests/unit/test_session_profile.py.
The recording route is the only caller.
"""

from __future__ import annotations

from typing import Any


def apply_health_profile(
    subject_metadata: dict[str, Any], patient: dict[str, Any], age_years: int | None = None
) -> None:
    """
    Snapshots the patient's self-reported health/demographic profile into this
    session's own static metadata at the moment recording starts — the whole
    point of collecting it once on the Patient record instead of re-asking
    every session. DatabaseManager.session_metadata has always had columns for
    subject_age/height/weight/vr_exp/vision_*/dominant_hand; nothing populated
    them before this, so they silently defaulted to "Unknown"/0.0 for every
    session ever recorded. Snapshotting (rather than joining session_metadata
    to patients.patient_id live) means editing a patient's profile later never
    silently rewrites what an already-recorded session's covariates were.
    """
    static_meta = subject_metadata.setdefault("M-IV_Static_Metadata", {})

    # Age arrives computed rather than derived here: PatientManager owns the
    # date_of_birth-vs-self-reported precedence, and a domain function must not
    # reach for a manager singleton to get it. Caught by ruff as an undefined
    # name when this moved out of src/main.py -- the one code path the
    # characterisation suite cannot reach, because starting a real recording
    # needs a headset.
    if age_years is not None:
        static_meta["subject_age"] = age_years
    if patient.get("biological_sex"):
        static_meta["subject_biological_sex"] = patient["biological_sex"]
    if patient.get("height_cm") is not None:
        static_meta["subject_height_cm"] = patient["height_cm"]
    if patient.get("weight_kg") is not None:
        static_meta["subject_weight_kg"] = patient["weight_kg"]
    if patient.get("vr_experience_level"):
        static_meta["subject_vr_exp"] = patient["vr_experience_level"]
    if patient.get("vision_correction"):
        static_meta["vision_correction"] = patient["vision_correction"]
    if patient.get("vision_impairment"):
        static_meta["vision_impairment"] = patient["vision_impairment"]

    # dominant_hand is read from C-V_Calibration by DatabaseManager.persist_experiment,
    # not M-IV_Static_Metadata — a different bucket than the rest of these fields.
    if patient.get("dominant_hand"):
        calib_meta = subject_metadata.setdefault("C-V_Calibration", {})
        calib_meta["dominant_hand"] = patient["dominant_hand"]


def default_anthropometrics(height_cm: float | None) -> dict[str, float]:
    """
    Height-based anthropometric estimates used as an editable *default* when
    the researcher doesn't directly measure arm length / shoulder width /
    standing eye height for a subject. Ratios are the commonly cited
    Drillis & Contini (1966) body-segment-to-stature proportions used
    throughout biomechanics for exactly this "no direct measurement
    available" situation — not a substitute for a real measurement, but a
    documented, reproducible estimate instead of the silent 0.0 every
    session recorded before this pipeline existed got.
    Returned in meters, matching how HMD/controller positions are recorded.
    """
    if not height_cm or height_cm <= 0:
        return {}
    height_m = height_cm / 100.0
    return {
        "arm_length_left": round(height_m * 0.44, 4),
        "arm_length_right": round(height_m * 0.44, 4),
        "shoulder_width_est": round(height_m * 0.259, 4),
        "neutral_head_height": round(height_m * 0.93, 4),
    }


def apply_calibration(
    subject_metadata: dict[str, Any], patient: dict[str, Any], config: Any
) -> None:
    """
    Populates C-V_Calibration with real (or best-effort-estimated) anthropometric
    baseline values instead of leaving neutral_head_height/shoulder_width_est/
    arm_length_left/right at persist_experiment's silent 0.0 default. These are
    the "necessary baseline variables to normalize physiological responses and
    calculate subject-specific kinematic reach constraints" — without them, every
    reach/kinematic metric downstream has nothing to normalize against.
    """
    calib_meta = subject_metadata.setdefault("C-V_Calibration", {})

    defaults = default_anthropometrics(patient.get("height_cm"))
    calib_meta.update(defaults)  # estimated baseline first...

    # ...then apply any researcher-entered measurement, which always wins over the estimate.
    if config.arm_length_left_cm is not None:
        calib_meta["arm_length_left"] = round(config.arm_length_left_cm / 100.0, 4)
    if config.arm_length_right_cm is not None:
        calib_meta["arm_length_right"] = round(config.arm_length_right_cm / 100.0, 4)
    if config.neutral_head_height_cm is not None:
        calib_meta["neutral_head_height"] = round(config.neutral_head_height_cm / 100.0, 4)
    if config.shoulder_width_cm is not None:
        calib_meta["shoulder_width_est"] = round(config.shoulder_width_cm / 100.0, 4)
