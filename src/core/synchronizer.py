import asyncio
import logging
from collections import deque
from typing import Optional

from src.core.datatypes import TelemetryFrame
from src.storage.parquet_writer import AsyncParquetWriter
from src.utils.hardware_monitor import HardwareMonitor
from src.core.live_state import LiveExperimentState
from src.core.derived_metrics import compute_binocular_focal_distance, compute_distance

logger = logging.getLogger(__name__)


class BiometricSynchronizer:
    """
    Lock-free ring buffer decoupling the hardware ingestion thread from the AsyncIO
    disk-writing thread. Also enforces an optional sampling-rate ceiling so bursty or
    duplicate-heavy sources (UDP floods, polling-loop artifacts) aren't recorded as if
    every burst were a unique physical sample.
    """

    def __init__(self, writer, hardware_monitor, buffer_size: int = 5000,
                 max_hz: Optional[float] = None, live_state: Optional[LiveExperimentState] = None):
        self.writer = writer
        self.hardware = hardware_monitor
        self.live_state = live_state
        
        self._buffer = deque(maxlen=buffer_size)
        self._is_running = False
        self._async_task: Optional[asyncio.Task] = None

        self.max_hz = max_hz
        self._min_interval_ns = int(1e9 / max_hz) if max_hz else None
        self._last_accepted_ts_ns: Optional[int] = None

        self.dropped_backpressure = 0   # buffer was full when we tried to append
        self.dropped_oversampling = 0   # frame arrived faster than the sampling cap allows
        self._last_backpressure_log = 0
        self._last_oversample_log = 0

    def set_max_hz(self, max_hz: float) -> None:
        """Adjust the sampling ceiling at runtime — e.g. once the real device refresh rate is known."""
        self.max_hz = max_hz
        self._min_interval_ns = int(1e9 / max_hz) if max_hz else None

    def push_frame(self, frame: TelemetryFrame) -> None:
        """Called directly by the hardware/ingestion thread. Must be non-blocking."""
        if self._min_interval_ns is not None and self._last_accepted_ts_ns is not None:
            delta = frame.timestamp_ns - self._last_accepted_ts_ns
            if 0 <= delta < self._min_interval_ns:
                self.dropped_oversampling += 1
                if self.dropped_oversampling - self._last_oversample_log >= 1000:
                    logger.warning(
                        f"Oversampling cap ({self.max_hz:.1f} Hz) rejected "
                        f"{self.dropped_oversampling} frame(s) so far — source is producing "
                        f"samples faster than the physical sensor rate."
                    )
                    self._last_oversample_log = self.dropped_oversampling
                return

        self._last_accepted_ts_ns = frame.timestamp_ns

        # Fold in the latest low-frequency hardware metrics — HardwareMonitor already
        # computes these on its own thread, but nothing previously copied them into frames.
        frame.cpu_utilization = self.hardware.cpu_usage
        frame.voice_amplitude_db = self.hardware.voice_db
        frame.gpu_utilization = self.hardware.gpu_usage
        frame.gaze_focal_distance = compute_binocular_focal_distance(frame)

        if self.live_state is not None:
            snap = self.live_state.snapshot()
            frame.scene_id = snap["scene_id"]
            frame.event_marker = snap["event_marker"]
            frame.haptic_left_intensity = snap["haptic_left_intensity"]
            frame.haptic_right_intensity = snap["haptic_right_intensity"]

            tx, ty, tz = snap["target_obj_pos"]
            frame.target_obj_pos_x, frame.target_obj_pos_y, frame.target_obj_pos_z = tx, ty, tz
            if frame.left_tracking_valid > 0:
                frame.dist_to_target_left = compute_distance(
                    (frame.left_pos_x, frame.left_pos_y, frame.left_pos_z), (tx, ty, tz))
            if frame.right_tracking_valid > 0:
                frame.dist_to_target_right = compute_distance(
                    (frame.right_pos_x, frame.right_pos_y, frame.right_pos_z), (tx, ty, tz))
                
        if len(self._buffer) >= self._buffer.maxlen:
            self.dropped_backpressure += 1
            if self.dropped_backpressure - self._last_backpressure_log >= 500:
                logger.warning(
                    f"Synchronizer buffer full — {self.dropped_backpressure} frame(s) dropped "
                    f"so far because the disk-writer thread is falling behind."
                )
                self._last_backpressure_log = self.dropped_backpressure

        self._buffer.append(frame.to_tuple())

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._is_running = True
        self._async_task = loop.create_task(self._consume_loop())
        cap_note = f" (sampling cap: {self.max_hz:.1f} Hz)" if self.max_hz else ""
        logger.info(f"Biometric synchronization buffer activated{cap_note}.")

    async def _consume_loop(self) -> None:
        while self._is_running or len(self._buffer) > 0:
            try:
                batch = []
                while len(self._buffer) > 0 and len(batch) < 120:
                    batch.append(self._buffer.popleft())

                if batch:
                    for frame_tuple in batch:
                        self.writer.push(frame_tuple)
                else:
                    await asyncio.sleep(0.001)

            except Exception as e:
                logger.error(f"Synchronizer Batch Error: {e}")

    def stop(self) -> None:
        self._is_running = False
        logger.info(
            f"Synchronizer shutting down. Flushing {len(self._buffer)} remaining frames to disk. "
            f"Dropped: {self.dropped_backpressure} (backpressure), "
            f"{self.dropped_oversampling} (oversampling cap)."
        )