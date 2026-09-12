"""compute_binocular_focal_distance, which had no coverage at all.

Written against the 12 Sep finding that every HTC session recorded
`gaze_focal_distance` as a constant 2.0: the HTC driver takes the
XR_EXT_eye_gaze_interaction path, which yields one *combined* gaze pose that
it writes into both the left and right slots. The vergence geometry is then
degenerate by construction, and the near-parallel fallback fired on every
frame of every session -- a constant sitting in the dataset looking like a
measurement.
"""

from src.core.datatypes import TelemetryFrame
from src.core.derived_metrics import compute_binocular_focal_distance

UNAVAILABLE = -1.0


def _frame(**overrides) -> TelemetryFrame:
    frame = TelemetryFrame.create_empty(0)
    frame.eye_tracking_valid = 1.0
    for key, value in overrides.items():
        setattr(frame, key, value)
    return frame


def test_invalid_eye_tracking_is_unavailable_not_zero():
    """0.0 would read as "focused at your own face"."""
    assert compute_binocular_focal_distance(_frame(eye_tracking_valid=0.0)) == UNAVAILABLE


def test_a_combined_gaze_ray_duplicated_into_both_eyes_is_unavailable():
    """The HTC path: one pose written to both slots, so there is no baseline.

    This is the case that used to return the 2.0 near-parallel fallback on
    every single frame.
    """
    frame = _frame(
        left_eye_pos_x=0.1,
        left_eye_pos_y=1.0,
        left_eye_pos_z=-0.05,
        right_eye_pos_x=0.1,
        right_eye_pos_y=1.0,
        right_eye_pos_z=-0.05,
        left_eye_rot_w=1.0,
        right_eye_rot_w=1.0,
    )

    assert compute_binocular_focal_distance(frame) == UNAVAILABLE


def test_genuinely_binocular_eyes_still_produce_a_distance():
    """A real per-eye driver must keep working: eyes apart, converging slightly."""
    frame = _frame(
        left_eye_pos_x=-0.032,
        left_eye_pos_y=1.6,
        left_eye_pos_z=0.0,
        right_eye_pos_x=0.032,
        right_eye_pos_y=1.6,
        right_eye_pos_z=0.0,
        # Yaw the two eyes toward each other so the rays actually cross.
        left_eye_rot_y=0.02,
        left_eye_rot_w=0.9998,
        right_eye_rot_y=-0.02,
        right_eye_rot_w=0.9998,
    )

    distance = compute_binocular_focal_distance(frame)

    assert distance > 0.0
    assert distance != UNAVAILABLE
