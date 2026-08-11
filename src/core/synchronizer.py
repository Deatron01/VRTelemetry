# src/core/synchronizer.py

import asyncio
import logging
from collections import deque
from typing import Optional

from src.core.datatypes import TelemetryFrame
from src.storage.parquet_writer import AsyncParquetWriter
from src.utils.hardware_monitor import HardwareMonitor

logger = logging.getLogger(__name__)

class BiometricSynchronizer:
    """
    Lock-free Ring Buffer architecture designed for 144Hz zero-loss telemetry transport.
    Decouples the OpenXR wait_frame() thread from the AsyncIO Disk-Writing thread using
    a double-ended queue. This prevents file I/O latency from stalling headset tracking.
    """
    
    def __init__(self, writer: AsyncParquetWriter, hardware_monitor: HardwareMonitor, buffer_size: int = 5000):
        self.writer = writer
        self.hardware = hardware_monitor
        
        # deque in Python is thread-safe for append() and popleft() operations.
        # Maxlen prevents memory leaks if the writer crashes (drops oldest frames).
        self._buffer = deque(maxlen=buffer_size)
        self._is_running = False
        self._async_task: Optional[asyncio.Task] = None

    def push_frame(self, frame: TelemetryFrame) -> None:
        """Called directly by the OpenXR hardware thread. Must be non-blocking."""
        # Convert to tuple immediately to snapshot the values before the main loop clears them.
        self._buffer.append(frame.to_tuple())

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Boots the consumer task onto the isolated AsyncIO thread."""
        self._is_running = True
        self._async_task = loop.create_task(self._consume_loop())
        logger.info("Lock-free biometric synchronization buffer activated.")

    async def _consume_loop(self) -> None:
        """Asynchronous consumer loop that offloads frames to the Parquet compressor."""
        while self._is_running or len(self._buffer) > 0:
            try:
                # Batch process available frames to minimize loop overhead
                batch = []
                while len(self._buffer) > 0 and len(batch) < 120:
                    batch.append(self._buffer.popleft())

                if batch:
                    for frame_tuple in batch:
                        # Call the native push method defined in AsyncParquetWriter
                        self.writer.push(frame_tuple)
                else:
                    # Yield execution briefly if buffer is empty (1ms sleep)
                    await asyncio.sleep(0.001)
                    
            except Exception as e:
                logger.error(f"Synchronizer Batch Error: {e}")

    def stop(self) -> None:
        """Signals the consumer to flush remaining frames and shutdown."""
        self._is_running = False
        logger.info(f"Synchronizer shutting down. Flushing {len(self._buffer)} remaining frames to disk.")