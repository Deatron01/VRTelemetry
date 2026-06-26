import pytest
import time
from src.core.datatypes import TelemetryFrame

@pytest.mark.unit
def test_telemetry_frame_creation():
    """Validates that empty frame creation provides safe 0.0 defaults, not NaNs."""
    frame = TelemetryFrame.create_empty(frame_idx=1)
    
    assert frame.frame_index == 1
    assert frame.hmd_pos_x == 0.0
    assert frame.hmd_tracking_valid == 0.0
    assert frame.eye_tracking_valid == 0.0
    assert frame.app_fps == 90.0

@pytest.mark.unit
def test_telemetry_frame_to_tuple_length():
    """Validates the flat vector mapping strictly matches the 64-dimensional AI requirement."""
    frame = TelemetryFrame.create_empty(0)
    flat_tuple = frame.to_tuple()
    
    # 64 elements required: 2 headers + 10 HMD + 12 L_Ctrl + 12 R_Ctrl + 15 Eye + 13 Sys
    assert len(flat_tuple) == 64
    assert isinstance(flat_tuple, tuple)
    
    # Ensure no dictionary overhead exists (__slots__ validation)
    with pytest.raises(AttributeError):
        _ = frame.__dict__