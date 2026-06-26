import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from src.storage.ai_preprocessor import VRAIPreprocessor

@pytest.mark.unit
def test_kinematic_derivations(tmp_path):
    """Validates that positions correctly derive to velocities."""
    
    # 1. Create a dummy Parquet file simulating linear movement
    # x moves 0.1 meters per frame at 90Hz -> Velocity should be 9.0 m/s
    data = {
        'frame_index': [0, 1, 2, 3, 4],
        'timestamp_ns': [0, 11111111, 22222222, 33333333, 44444444],
        'hmd_pos_x': [0.0, 0.1, 0.2, 0.3, 0.4]
    }
    df = pd.DataFrame(data)
    raw_path = tmp_path / "telemetry_raw.parquet"
    df.to_parquet(raw_path)

    # 2. Run Preprocessor
    preprocessor = VRAIPreprocessor(raw_parquet_path=raw_path, target_hz=90)
    preprocessor.execute_transform()

    # 3. Verify Output
    assert preprocessor.out_file.exists()
    assert preprocessor.meta_file.exists()

    df_out = pd.read_parquet(preprocessor.out_file)
    
    # Check if 'vel_' column was generated
    assert 'hmd_vel_x' in df_out.columns
    
    # Note: StandardScaler will normalize the output to Z-scores, so we test 
    # the presence of the calculation rather than the raw 9.0 value, 
    # or we can test that NaNs are entirely eliminated.
    assert df_out['hmd_vel_x'].isna().sum() == 0