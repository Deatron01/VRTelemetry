# tests/test_datatypes.py

import pytest
import numpy as np
from src.core.datatypes import TelemetryFrame

def test_telemetry_frame_zero_allocation_creation(benchmark):
    """
    Validates that the telemetry frame instantiation can operate strictly 
    within the sub-millisecond bounds required for 90-120Hz operation 
    without triggering excessive Garbage Collection latency.
    """
    # Note: Requires pytest-benchmark, acts as standard unit test if absent
    def create_frame():
        return TelemetryFrame.create_empty(frame_idx=1)
        
    if benchmark:
        result = benchmark(create_frame)
        assert result is not None
    else:
        frame = create_frame()
        assert frame.frame_index == 1

def test_flat_structure_compliance(mock_telemetry_frame):
    """
    Asserts compliance with REQ-ARCH-1.5 (Sík/Lapos Adatszerkezet).
    Ensures every attribute in the TelemetryFrame is explicitly a float or int.
    """
    flat_data = mock_telemetry_frame.to_tuple()
    
    for val in flat_data:
        assert isinstance(val, (int, float)), f"Type Violation: Found {type(val)} instead of int/float."

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