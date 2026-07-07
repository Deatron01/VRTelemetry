# tests/unit/test_preprocessor.py

import pytest
import numpy as np
from src.core.datatypes import TelemetryFrame

def test_telemetry_frame_memory_layout():
    """
    Validates Requirement 1.5 (Sík/Lapos Adatszerkezet):
    Ensures that the primary data transfer object is 1-Dimensional and 
    capable of direct serialization into a uniform length matrix.
    """
    frame = TelemetryFrame.create_empty(frame_idx=1)
    
    # Generate tuple configuration
    flat_data = frame.to_tuple()
    
    # Assert length matches the exact Parquet columnar specification (67 Columns defined in datatypes)
    assert len(flat_data) == 67, f"Schema mismatch: Expected 67 columns, got {len(flat_data)}"
    
    # Ensure nested types (dicts, lists) are forbidden at runtime
    for item in flat_data:
        assert isinstance(item, (int, float)), f"Type violation: Field type {type(item)} detected, only Int/Float allowed."

def test_telemetry_frame_type_casting():
    """
    Validates standard machine learning tensor generation pipelines directly
    from the raw TelemetryFrame objects, verifying float32 compatibility.
    """
    frame = TelemetryFrame.create_empty(frame_idx=1)
    flat_data = frame.to_tuple()
    
    # Cast to NumPy Array simulating PyTorch DataLoader ingestion
    tensor = np.array(flat_data, dtype=np.float32)
    
    assert tensor.ndim == 1, "Tensor shape violation: Result is not 1-Dimensional."
    assert tensor.shape[0] == 67, "Tensor length violation."