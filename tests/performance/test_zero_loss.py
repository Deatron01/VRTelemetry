import time
import pytest
import pandas as pd
from src.core.engine import TelemetryEngine

@pytest.mark.stress
def test_120hz_zero_loss_stability(mock_backend, temp_session_dir):
    """
    Stress tests the core telemetry loop at 120Hz for a sustained burst.
    Validates that the microsecond spin-lock maintains the target delta-T 
    without dropping frames or triggering the OS garbage collector excessively.
    """
    target_hz = 120
    duration_seconds = 5 # 600 frames
    ideal_dt = 1.0 / target_hz
    tolerance = ideal_dt * 1.5 # 1.5x delay is considered a dropped frame
    
    engine = TelemetryEngine(target_hz=target_hz, output_dir=str(temp_session_dir))
    engine.backend = mock_backend
    
    start_time = time.perf_counter()
    engine.is_running = True
    engine.writer.start()
    
    # 1. Execute the hybrid spin-lock loop manually for testing assertions
    for _ in range(target_hz * duration_seconds):
        frame = engine.backend.poll_frame(engine.frames_recorded)
        engine.writer.push(frame)
        engine.frames_recorded += 1
        
        next_frame_time = start_time + (engine.frames_recorded * ideal_dt)
        now = time.perf_counter()
        
        if next_frame_time - now > 0.002:
            time.sleep((next_frame_time - now) - 0.002)
        while time.perf_counter() < next_frame_time:
            pass
            
    engine._teardown()
    
    # 2. Mathematical Validation of the resulting Parquet Tensor
    assert engine.parquet_path.exists()
    df = pd.read_parquet(engine.parquet_path)
    
    assert len(df) == 600, f"Expected 600 frames, got {len(df)}"
    
    # Calculate inter-frame timing delta
    df['time_sec'] = df['timestamp_ns'] / 1e9
    df['delta_time'] = df['time_sec'].diff().fillna(ideal_dt)
    
    # Assert that no frame took longer than the 1.5x tolerance
    dropped_frames = df[df['delta_time'] > tolerance]
    assert len(dropped_frames) == 0, f"Engine dropped {len(dropped_frames)} frames at 120Hz."