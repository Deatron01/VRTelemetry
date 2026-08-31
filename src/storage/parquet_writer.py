# src/storage/parquet_writer.py

import logging
import os
import threading
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


class AsyncParquetWriter:
    """
    High-throughput columnar data sink. Buffers 1D telemetry vectors in memory
    and flushes them to disk asynchronously to prevent blocking the high-frequency
    hardware acquisition loops. Ensures strict Float32 compliance for AI ingestion.
    """

    def __init__(
        self,
        output_path: Path,
        target_hz: int = 90,
        flush_interval_frames: int = 900,
        max_consecutive_failures: int = 5,
    ):
        self.output_path = output_path
        self.target_hz = target_hz
        self.flush_interval = flush_interval_frames

        self.buffer: list[tuple] = []
        self.is_running = False
        self._lock = threading.Lock()

        self.writer: pq.ParquetWriter = None
        self._file_obj = None
        self._schema = self._define_schema()

        # Failure tracking — a stuck flush must not retry silently forever while the
        # in-memory buffer grows without bound and the engine reports frames as "recorded"
        # that never actually reached disk.
        self.consecutive_write_failures = 0
        self.max_consecutive_failures = max_consecutive_failures
        self.write_failed = False
        # Hard ceiling on in-memory buffer size regardless of flush_interval, so a stalled
        # disk can't turn this into an unbounded memory leak before the failure threshold trips.
        self._max_buffer_size = flush_interval_frames * 10

    def _define_schema(self) -> pa.Schema:
        """
        Defines the strict memory layout for the PyArrow matrix. Enforces 32-bit floating
        point types to halve VRAM requirements during downstream PyTorch training.
        Fields are strictly ordered according to the REQ Specification (Cat 2 & 7).
        """
        return pa.schema(
            [
                ("frame_index", pa.int64()),
                ("timestamp_ns", pa.int64()),
                ("hmd_pos_x", pa.float32()),
                ("hmd_pos_y", pa.float32()),
                ("hmd_pos_z", pa.float32()),
                ("hmd_rot_x", pa.float32()),
                ("hmd_rot_y", pa.float32()),
                ("hmd_rot_z", pa.float32()),
                ("hmd_rot_w", pa.float32()),
                ("left_pos_x", pa.float32()),
                ("left_pos_y", pa.float32()),
                ("left_pos_z", pa.float32()),
                ("left_rot_x", pa.float32()),
                ("left_rot_y", pa.float32()),
                ("left_rot_z", pa.float32()),
                ("left_rot_w", pa.float32()),
                ("left_trigger", pa.float32()),
                ("left_grip", pa.float32()),
                ("left_joy_x", pa.float32()),
                ("left_joy_y", pa.float32()),
                ("right_pos_x", pa.float32()),
                ("right_pos_y", pa.float32()),
                ("right_pos_z", pa.float32()),
                ("right_rot_x", pa.float32()),
                ("right_rot_y", pa.float32()),
                ("right_rot_z", pa.float32()),
                ("right_rot_w", pa.float32()),
                ("right_trigger", pa.float32()),
                ("right_grip", pa.float32()),
                ("right_joy_x", pa.float32()),
                ("right_joy_y", pa.float32()),
                ("left_eye_pos_x", pa.float32()),
                ("left_eye_pos_y", pa.float32()),
                ("left_eye_pos_z", pa.float32()),
                ("left_eye_rot_x", pa.float32()),
                ("left_eye_rot_y", pa.float32()),
                ("left_eye_rot_z", pa.float32()),
                ("left_eye_rot_w", pa.float32()),
                ("right_eye_pos_x", pa.float32()),
                ("right_eye_pos_y", pa.float32()),
                ("right_eye_pos_z", pa.float32()),
                ("right_eye_rot_x", pa.float32()),
                ("right_eye_rot_y", pa.float32()),
                ("right_eye_rot_z", pa.float32()),
                ("right_eye_rot_w", pa.float32()),
                ("hmd_tracking_valid", pa.float32()),
                ("left_tracking_valid", pa.float32()),
                ("right_tracking_valid", pa.float32()),
                ("eye_tracking_valid", pa.float32()),
                ("left_pupil_size", pa.float32()),
                ("right_pupil_size", pa.float32()),
                ("heart_rate_bpm", pa.float32()),
                ("distance_to_boundary", pa.float32()),
                ("app_fps", pa.float32()),
                ("event_marker", pa.float32()),
                ("battery_hmd", pa.float32()),
                ("battery_left", pa.float32()),
                ("battery_right", pa.float32()),
                ("haptic_left_intensity", pa.float32()),
                ("haptic_right_intensity", pa.float32()),
                ("gaze_focal_distance", pa.float32()),
                ("voice_amplitude_db", pa.float32()),
                ("cpu_utilization", pa.float32()),
                ("gpu_utilization", pa.float32()),
                ("scene_id", pa.float32()),
                ("target_obj_pos_x", pa.float32()),
                ("target_obj_pos_y", pa.float32()),
                ("target_obj_pos_z", pa.float32()),
                ("dist_to_target_left", pa.float32()),
                ("dist_to_target_right", pa.float32()),
            ]
        )

    def start(self) -> None:
        """Initializes the Parquet binary file stream and readies the ingestion buffers."""
        try:
            # Open the file object ourselves so we can fsync it on every flush interval —
            # see _flush_buffer_to_disk. Without this, a hard power loss between flushes
            # could lose data that "looked written" but was only sitting in OS buffers.
            self._file_obj = open(str(self.output_path), "wb")
            self.writer = pq.ParquetWriter(
                self._file_obj, self._schema, compression="snappy", use_dictionary=False
            )
            self.is_running = True
            self.write_failed = False
            self.consecutive_write_failures = 0
            logger.info(f"Parquet storage pipeline opened: {self.output_path.name}")
        except Exception as e:
            logger.error(f"Failed to initialize Parquet writer: {e}")
            raise

    def push(self, frame_tuple: tuple) -> None:
        """
        Receives isolated frames from the Synchronizer queue. When the batch size
        threshold is reached, the buffer is rotated and flushed to disk.
        """
        if not self.is_running:
            return

        if self.write_failed:
            # The disk writer has already given up after repeated failures. Continuing to
            # accept frames here would just grow an unbounded in-memory buffer for data that
            # will never be persisted — drop instead, the failure is already logged/flagged.
            return

        with self._lock:
            self.buffer.append(frame_tuple)

            if len(self.buffer) > self._max_buffer_size:
                overflow = len(self.buffer) - self._max_buffer_size
                del self.buffer[:overflow]
                logger.warning(
                    f"Parquet buffer exceeded hard ceiling ({self._max_buffer_size} frames) — "
                    f"dropped {overflow} oldest frame(s) rather than growing without bound."
                )

            if len(self.buffer) >= self.flush_interval:
                self._flush_buffer_to_disk()

    def _flush_buffer_to_disk(self) -> None:
        """
        Transmutes the list of tuples into columnar Arrow Arrays and persists to disk.
        Executes within the lock boundary to prevent race conditions during buffer swap.
        """
        if not self.buffer:
            return

        try:
            columns = list(zip(*self.buffer))

            arrays = [pa.array(columns[i], type=field.type) for i, field in enumerate(self._schema)]

            batch = pa.RecordBatch.from_arrays(arrays, schema=self._schema)
            table = pa.Table.from_batches([batch])
            self.writer.write_table(table)

            # Force the row group out of the OS page cache and onto physical storage so a
            # crash right after this point can lose at most the *next* interval's worth of
            # frames, not this one that already "successfully" flushed.
            try:
                self._file_obj.flush()
                os.fsync(self._file_obj.fileno())
            except Exception as fsync_err:
                logger.debug(
                    f"fsync after flush failed (non-fatal, data still buffered by OS): {fsync_err}"
                )

            self.buffer.clear()
            self.consecutive_write_failures = 0

        except Exception as e:
            self.consecutive_write_failures += 1
            logger.error(
                f"Critical disk write failure during Parquet flush "
                f"(consecutive failures: {self.consecutive_write_failures}/{self.max_consecutive_failures}): {e}"
            )

            if self.consecutive_write_failures >= self.max_consecutive_failures:
                self.write_failed = True
                self.is_running = False
                logger.critical(
                    f"Parquet writer failed {self.consecutive_write_failures} consecutive flush(es) for "
                    f"{self.output_path.name} — halting ingestion. Frames captured from this point onward "
                    f"are NOT being persisted to disk."
                )

    def stop(self) -> None:
        """Flushes residual frames and securely closes the binary writer handle."""
        self.is_running = False
        with self._lock:
            if len(self.buffer) > 0:
                self._flush_buffer_to_disk()
            if self.writer:
                try:
                    self.writer.close()
                    logger.info("Parquet storage pipeline sealed successfully.")
                except Exception as e:
                    logger.error(f"Error sealing Parquet writer: {e}")
            if self._file_obj:
                try:
                    self._file_obj.close()
                except Exception as e:
                    logger.debug(f"Error closing underlying file handle: {e}")
