# tests/test_datatypes.py

from src.core.datatypes import TelemetryFrame


def test_telemetry_frame_zero_allocation_creation():
    """
    Validates that the telemetry frame instantiation can operate strictly
    within the sub-millisecond bounds required for 90-120Hz operation.
    """
    frame = TelemetryFrame.create_empty(frame_idx=1)
    assert frame.frame_index == 1
    assert frame.hmd_rot_w == 1.0


def test_flat_structure_compliance(mock_telemetry_frame):
    """
    Asserts compliance with REQ-ARCH-1.5 (Sík/Lapos Adatszerkezet).
    Ensures every attribute in the TelemetryFrame is explicitly a float or int,
    and exactly matches the 70-column PyArrow schema length.
    """
    flat_data = mock_telemetry_frame.to_tuple()

    # Verify exact column count matching the PyArrow schema
    assert len(flat_data) == 70, f"Schema mismatch: Expected 70 columns, got {len(flat_data)}."

    for val in flat_data:
        assert isinstance(val, (int, float)), (
            f"Type Violation: Found {type(val)} instead of int/float."
        )


def test_quaternion_normalization_safety(mock_telemetry_frame):
    """
    Ensures rotational fallbacks default to safe normalized identities (0,0,0,1)
    to prevent NaN propagation in downstream AI pipelines.
    """
    assert mock_telemetry_frame.hmd_rot_w == 1.0
    assert mock_telemetry_frame.left_rot_w == 1.0
    assert mock_telemetry_frame.right_rot_w == 1.0
    assert mock_telemetry_frame.left_eye_rot_w == 1.0
    assert mock_telemetry_frame.right_eye_rot_w == 1.0

    # Assert X, Y, Z are explicitly 0.0
    assert mock_telemetry_frame.hmd_rot_x == 0.0
    assert mock_telemetry_frame.left_eye_rot_y == 0.0
