"""Tests for subject profile and anthropometric baselines (VRT-10).

These functions had no coverage at all. They sat in ``src/main.py`` taking a
``TelemetryEngine``, and the only route that calls them --
``POST /api/recording/start`` -- cannot complete without a headset, so the
characterisation suite reaches its guard clauses and stops there.

Moving them to ``src/domain/`` and giving them a plain metadata dict instead of
an engine is what makes them testable at all. That change immediately paid for
itself: ruff found ``apply_health_profile`` referencing a ``_patients``
singleton that no longer existed in its new module -- an undefined name on a
path nothing executes, which would have surfaced as a crash the first time a
researcher started a recording.
"""

from __future__ import annotations

import pytest

from src.domain.session_profile import (
    apply_calibration,
    apply_health_profile,
    default_anthropometrics,
)

PATIENT = {
    "patient_id": "pat-1",
    "biological_sex": "female",
    "height_cm": 170.0,
    "weight_kg": 65.0,
    "vr_experience_level": "intermediate",
    "vision_correction": "glasses",
    "vision_impairment": "none",
    "dominant_hand": "left",
}


class _Config:
    """Stand-in for SessionStartConfig: only the four override fields matter."""

    def __init__(self, **kwargs: float | None) -> None:
        self.arm_length_left_cm = kwargs.get("arm_length_left_cm")
        self.arm_length_right_cm = kwargs.get("arm_length_right_cm")
        self.neutral_head_height_cm = kwargs.get("neutral_head_height_cm")
        self.shoulder_width_cm = kwargs.get("shoulder_width_cm")


# --------------------------------------------------------------------------- #
# Anthropometric estimates
# --------------------------------------------------------------------------- #


def test_estimates_follow_the_drillis_and_contini_ratios() -> None:
    """The published body-segment-to-stature proportions, at 1.70 m."""
    result = default_anthropometrics(170.0)

    assert result["arm_length_left"] == pytest.approx(1.70 * 0.44, abs=1e-4)
    assert result["arm_length_right"] == pytest.approx(1.70 * 0.44, abs=1e-4)
    assert result["shoulder_width_est"] == pytest.approx(1.70 * 0.259, abs=1e-4)
    assert result["neutral_head_height"] == pytest.approx(1.70 * 0.93, abs=1e-4)


def test_estimates_are_returned_in_metres() -> None:
    """HMD and controller positions are recorded in metres; these must match.

    A unit mismatch here would not raise -- it would silently make every
    normalised reach and kinematic metric wrong by a factor of 100.
    """
    result = default_anthropometrics(180.0)

    assert all(0.1 < value < 2.5 for value in result.values()), result


@pytest.mark.parametrize("height", [None, 0, -5])
def test_no_estimate_without_a_usable_height(height: float | None) -> None:
    """Better an absent baseline than one derived from a nonsense height."""
    assert default_anthropometrics(height) == {}


# --------------------------------------------------------------------------- #
# Health profile snapshot
# --------------------------------------------------------------------------- #


def test_health_profile_is_snapshotted_into_static_metadata() -> None:
    """Snapshotted, not joined live: editing a patient later must never rewrite
    what an already-recorded session's covariates were."""
    metadata: dict = {}

    apply_health_profile(metadata, PATIENT, age_years=31)

    static = metadata["M-IV_Static_Metadata"]
    assert static["subject_age"] == 31
    assert static["subject_biological_sex"] == "female"
    assert static["subject_height_cm"] == 170.0
    assert static["subject_weight_kg"] == 65.0
    assert static["subject_vr_exp"] == "intermediate"
    assert static["vision_correction"] == "glasses"


def test_dominant_hand_goes_to_the_calibration_bucket_not_the_static_one() -> None:
    """A real quirk worth pinning: DatabaseManager.persist_experiment reads
    dominant_hand from C-V_Calibration, unlike every other profile field."""
    metadata: dict = {}

    apply_health_profile(metadata, PATIENT, age_years=31)

    assert metadata["C-V_Calibration"]["dominant_hand"] == "left"
    assert "dominant_hand" not in metadata["M-IV_Static_Metadata"]


def test_absent_fields_are_left_absent_rather_than_defaulted() -> None:
    """Writing "Unknown" over a field nobody measured is worse than omitting it."""
    metadata: dict = {}

    apply_health_profile(metadata, {"patient_id": "pat-2"}, age_years=None)

    assert metadata.get("M-IV_Static_Metadata", {}) == {}


def test_existing_metadata_is_preserved() -> None:
    """The engine has already put session_id and subject_id here."""
    metadata = {"M-IV_Static_Metadata": {"session_id": "20260527_133428"}}

    apply_health_profile(metadata, PATIENT, age_years=31)

    assert metadata["M-IV_Static_Metadata"]["session_id"] == "20260527_133428"
    assert metadata["M-IV_Static_Metadata"]["subject_height_cm"] == 170.0


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #


def test_calibration_falls_back_to_the_height_estimate() -> None:
    metadata: dict = {}

    apply_calibration(metadata, PATIENT, _Config())

    assert metadata["C-V_Calibration"]["arm_length_left"] == pytest.approx(0.748, abs=1e-3)


def test_a_measured_value_always_beats_the_estimate() -> None:
    """The whole point: the estimate is a documented default, not a substitute
    for a researcher actually measuring the subject."""
    metadata: dict = {}

    apply_calibration(metadata, PATIENT, _Config(arm_length_left_cm=71.0))

    calib = metadata["C-V_Calibration"]
    assert calib["arm_length_left"] == pytest.approx(0.71, abs=1e-4)
    assert calib["arm_length_right"] == pytest.approx(0.748, abs=1e-3)  # still estimated


def test_measurements_are_converted_from_centimetres_to_metres() -> None:
    metadata: dict = {}

    apply_calibration(
        metadata,
        PATIENT,
        _Config(neutral_head_height_cm=158.0, shoulder_width_cm=44.0),
    )

    calib = metadata["C-V_Calibration"]
    assert calib["neutral_head_height"] == pytest.approx(1.58, abs=1e-4)
    assert calib["shoulder_width_est"] == pytest.approx(0.44, abs=1e-4)


def test_calibration_without_a_height_or_measurements_stays_empty() -> None:
    """Persisting a silent 0.0 is what this whole mechanism exists to avoid."""
    metadata: dict = {}

    apply_calibration(metadata, {"patient_id": "pat-3"}, _Config())

    assert metadata["C-V_Calibration"] == {}
