# tests/performance/test_zero_loss.py

import time
import pytest
import threading
from src.core.datatypes import TelemetryFrame
from src.core.synchronizer import BiometricSynchronizer
from src.storage.parquet_writer import AsyncParquetWriter
from src.utils.hardware_monitor import HardwareMonitor

@pytest.fixture
def mock_writer(tmp_path):
    # Overwrite async Parquet writer to write to a temporary disk location safely
    parquet_path = tmp_path / "zero_loss_test.parquet"
    writer = AsyncParquetWriter(output_path=parquet_path, target_hz=90, flush_interval_frames=50)
    writer.start()
    yield writer
    writer.stop()

@pytest.fixture
def hardware_stub():
    hw = HardwareMonitor(target_hz=10)
    # Don't actually boot the thread to isolate variables, just pass the object
    return hw

@pytest.mark.asyncio
async def test_synchronizer_queue_throughput(mock_writer, hardware_stub):
    """
    Validates Requirement ARCH-1.1 (Zero-Loss Adatgyűjtés).
    Pushes 10,000 frames (approx 110 seconds of 90Hz telemetry) into the 
    lock-free ring buffer asynchronously while simultaneously consuming them,
    asserting 0 frames are dropped due to thread starvation or I/O blocking.
    """
    import asyncio
    
    sync = BiometricSynchronizer(writer=mock_writer, hardware_monitor=hardware_stub)
    
    loop = asyncio.get_running_loop()
    sync.start(loop)
    
    total_frames_target = 10000
    produced_frames = 0
    
    # Producer Simulation (Simulates the OpenXR strict hardware polling loop)
    def fast_producer():
        nonlocal produced_frames
        for i in range(total_frames_target):
            # Create a mock float32 telemetry state vector
            frame = TelemetryFrame.create_empty(i)
            sync.push_frame(frame)
            produced_frames += 1
            
            # Artificial sleep mimicking 90Hz interval to prevent unrealistic memory flood (11ms)
            # Shortened to 0.1ms for test speed, vastly exceeding real-world pressure constraints
            time.sleep(0.0001) 
            
    producer_thread = threading.Thread(target=fast_producer)
    producer_thread.start()
    
    producer_thread.join(timeout=5.0)
    
    # Wait for the async consumer loop to drain the queue entirely
    drain_timeout = time.time() + 3.0
    while not sync.queue.empty():
        if time.time() > drain_timeout:
            pytest.fail("Synchronizer consumer thread failed to drain queue in time. Possible lock-contention detected.")
        await asyncio.sleep(0.1)
        
    sync.stop()
    
    # Force parity checks
    assert produced_frames == total_frames_target, f"Producer mismatch: {produced_frames} != {total_frames_target}"
    assert sync.queue.empty(), "Memory leak: Frame queue is not empty after execution seal."
    
    # Writer validation (Wait for lock release during shutdown)
    time.sleep(0.1)
    # Using PyArrow to read and verify identical row count
    import pyarrow.parquet as pq
    table = pq.read_table(mock_writer.output_path)
    
    assert table.num_rows == total_frames_target, f"Disk I/O failure: Expected {total_frames_target} Parquet rows, got {table.num_rows}. Frame drop detected!"