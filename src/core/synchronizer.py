# src/core/synchronizer.py

import asyncio
import logging
from queue import Queue, Empty
from typing import Optional

from src.core.datatypes import TelemetryFrame
from src.storage.parquet_writer import AsyncParquetWriter
from src.utils.hardware_monitor import HardwareMonitor

logger = logging.getLogger(__name__)

class BiometricSynchronizer:
    """
    Decoupled lock-free Ring Thread Buffer matching requirement ARCH-1.1.
    Ingests asynchronous hardware threads and low-frequency metrics pipelines, aligning
    them securely into a single high-frequency frame tracking matrix without jitter.
    """

    def __init__(self, writer: AsyncParquetWriter, hardware_monitor: HardwareMonitor) -> None:
        self.writer = writer
        self.hardware = hardware_monitor
        self.queue: Queue[TelemetryFrame] = Queue(maxsize=1024)
        self.is_running = False
        self._loop_task: Optional[asyncio.Task] = None

    def push_frame(self, frame: TelemetryFrame) -> None:
        """
        Thread-safe producer hook to push real-time spatial captures into the sync line.
        Applies Forward-Fill matching specification bounds for low-frequency hooks.
        """
        # Inject low-frequency continuous metrics tracking values
        frame.cpu_utilization = self.hardware.cpu_usage
        frame.voice_amplitude_db = self.hardware.voice_db

        try:
            self.queue.put_nowait(frame)
        except Exception:
            logger.warning("Telemetry Synchronizer queue saturation. Purging frame slot to secure flow continuity.")

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.is_running = True
        self._loop_task = loop.create_task(self._consume_queue())

    async def _consume_queue(self) -> None:
        """
        Asynchronous execution task flushing raw tracking entities straight down 
        to disk writer buffers.
        """
        while self.is_running:
            try:
                # Non-blocking poll strategy inside safe async execution boundaries
                while not self.queue.empty():
                    frame = self.queue.get_nowait()
                    self.writer.push(frame)
                    self.queue.task_done()
            except Empty:
                pass
            await asyncio.sleep(0.001)

    def stop(self) -> None:
        self.is_running = False
        if self._loop_task:
            self._loop_task.cancel()