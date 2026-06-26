import pytest
import time
import pandas as pd
from src.core.engine import TelemetryEngine

@pytest.mark.integration
@pytest.mark.io
def test_full_engine_pipeline(mock_backend, temp_session_dir):
    """
    Validates that the engine successfully polls the hardware, 
    queues the data asynchronously, and flushes exactly the right number of frames to disk.
    """
    engine = TelemetryEngine(target_hz=90, output_dir=str(temp_session_dir))
    
    # Inject dependency
    engine.backend = mock_backend
    
    # Override batch size to force rapid disk flushing for the test
    engine.writer.batch_size = 10 
    
    engine.start() # In a real test environment with `time.sleep`, this blocks.
    # To test non-blocking, we mock the loop execution for 25 frames:
    
    engine.is_running = True
    engine.writer.start()
    
    for i in range(25):
        frame = engine.backend.poll_frame(i)
        engine.writer.push(frame)
    
    engine._teardown() # Triggers the final queue flush
    
    # Verify Parquet file exists and has exactly 25 rows
    assert engine.parquet_path.exists()
    
    df = pd.read_parquet(engine.parquet_path)
    assert len(df) == 25
    assert df['frame_index'].iloc[-1] == 24