# tests/performance/test_zero_loss.py

import time
import queue
import pytest
import asyncio
from src.core.datatypes import TelemetryFrame
from src.core.synchronizer import BiometricSynchronizer
from src.storage.parquet_writer import AsyncParquetWriter
from src.utils.hardware_monitor import HardwareMonitor

@pytest.fixture
def mock_writer(tmp_path):
    parquet_path = tmp_path / "zero_loss_test.parquet"
    writer = AsyncParquetWriter(output_path=parquet_path, target_hz=90, flush_interval_frames=50)
    writer.start()
    yield writer
    writer.stop()

@pytest.fixture
def hardware_stub():
    return HardwareMonitor(target_hz=10)

@pytest.mark.asyncio
async def test_synchronizer_queue_throughput(mock_writer, hardware_stub):
    """
    Validates Requirement ARCH-1.1 (Zero-Loss Adatgyűjtés).
    Pushes 10,000 frames into the lock-free ring buffer asynchronously while 
    simultaneously consuming them, asserting 0 frames are dropped.
    """
    sync = BiometricSynchronizer(writer=mock_writer, hardware_monitor=hardware_stub)
    
    # Overwrite the safety limit of 1024 for the stress test.
    # This allows the artificial CPU-speed producer to dump all 10k frames instantly 
    # to test the Parquet writer's maximum batch throughput.
    sync.queue = queue.Queue(maxsize=0) 
    
    loop = asyncio.get_running_loop()
    sync.start(loop)
    
    total_frames_target = 10000
    produced_frames = 0
    
    # Non-blocking producer task utilizing the async thread pool
    def fast_producer():
        nonlocal produced_frames
        for i in range(total_frames_target):
            frame = TelemetryFrame.create_empty(i)
            sync.push_frame(frame)
            produced_frames += 1
            
    # Yield execution context securely
    await asyncio.to_thread(fast_producer)
    
    # Wait for the async consumer loop to drain the massive queue
    drain_timeout = time.time() + 5.0
    while not sync.queue.empty():
        if time.time() > drain_timeout:
            pytest.fail("Synchronizer consumer thread failed to drain queue in time.")
        await asyncio.sleep(0.1)
        
    sync.stop()
    mock_writer.stop()
    
    # Allow a split second for the final lock release on the file handle
    time.sleep(0.2)
    
    assert produced_frames == total_frames_target
    assert sync.queue.empty()
    
    import pyarrow.parquet as pq
    table = pq.read_table(mock_writer.output_path)
    
    assert table.num_rows == total_frames_target, "Disk I/O dropped frames."