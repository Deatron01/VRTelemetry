import pytest
import time
from pathlib import Path
from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame

class MockVRBackend(IVRBackend):
    """A simulated hardware backend that generates deterministic sine-wave telemetry."""
    def __init__(self, target_hz: int = 90):
        self.target_hz = target_hz
        self.start_time = time.perf_counter()

    def initialize(self) -> bool:
        return True

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        t = time.perf_counter() - self.start_time
        
        import math
        # Simulate moving HMD
        frame.hmd_pos_x = math.sin(t * 2.0)
        frame.hmd_pos_y = 1.6 + math.cos(t * 1.5) * 0.1
        frame.hmd_pos_z = math.cos(t * 2.0)
        frame.hmd_tracking_valid = 1.0
        
        return frame

    def shutdown(self) -> None:
        pass

@pytest.fixture
def mock_backend():
    return MockVRBackend(target_hz=90)

@pytest.fixture
def temp_session_dir(tmp_path):
    """Provides a temporary, auto-cleaning directory for Parquet/SQL I/O tests."""
    d = tmp_path / "Sessions"
    d.mkdir()
    return d