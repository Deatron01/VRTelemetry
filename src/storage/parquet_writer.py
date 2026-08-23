# src/storage/parquet_writer.py

import os
import threading
import logging
from typing import List, Tuple
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

    def __init__(self, output_path: Path, target_hz: int = 90, flush_interval_frames: int = 900):
        self.output_path = output_path
        self.target_hz = target_hz
        self.flush_interval = flush_interval_frames
        
        self.buffer: List[tuple] = []
        self.is_running = False
        self._lock = threading.Lock()
        
        self.writer: pq.ParquetWriter = None
        self._schema = self._define_schema()

    def _define_schema(self) -> pa.Schema:
        """
        Defines the strict memory layout for the PyArrow matrix. Enforces 32-bit floating 
        point types to halve VRAM requirements during downstream PyTorch training.
        Fields are strictly ordered according to the REQ Specification (Cat 2 & 7).
        """
        return pa.schema([
            ("frame_index", pa.int64()),
            ("timestamp_ns", pa.int64()),
            
            # 1. HMD Kinematics (2.3 - 2.9)
            ("hmd_pos_x", pa.float32()), ("hmd_pos_y", pa.float32()), ("hmd_pos_z", pa.float32()),
            ("hmd_rot_x", pa.float32()), ("hmd_rot_y", pa.float32()), ("hmd_rot_z", pa.float32()), ("hmd_rot_w", pa.float32()),
            
            # 2. Left Controller (2.10 - 2.20)
            ("left_pos_x", pa.float32()), ("left_pos_y", pa.float32()), ("left_pos_z", pa.float32()),
            ("left_rot_x", pa.float32()), ("left_rot_y", pa.float32()), ("left_rot_z", pa.float32()), ("left_rot_w", pa.float32()),
            ("left_trigger", pa.float32()), ("left_grip", pa.float32()), ("left_joy_x", pa.float32()), ("left_joy_y", pa.float32()),
            
            # 3. Right Controller (2.21 - 2.31)
            ("right_pos_x", pa.float32()), ("right_pos_y", pa.float32()), ("right_pos_z", pa.float32()),
            ("right_rot_x", pa.float32()), ("right_rot_y", pa.float32()), ("right_rot_z", pa.float32()), ("right_rot_w", pa.float32()),
            ("right_trigger", pa.float32()), ("right_grip", pa.float32()), ("right_joy_x", pa.float32()), ("right_joy_y", pa.float32()),
            
            # 4. Eye Tracking Left (2.32 - 2.38)
            ("left_eye_pos_x", pa.float32()), ("left_eye_pos_y", pa.float32()), ("left_eye_pos_z", pa.float32()),
            ("left_eye_rot_x", pa.float32()), ("left_eye_rot_y", pa.float32()), ("left_eye_rot_z", pa.float32()), ("left_eye_rot_w", pa.float32()),
            
            # 5. Eye Tracking Right (2.39 - 2.45)
            ("right_eye_pos_x", pa.float32()), ("right_eye_pos_y", pa.float32()), ("right_eye_pos_z", pa.float32()),
            ("right_eye_rot_x", pa.float32()), ("right_eye_rot_y", pa.float32()), ("right_eye_rot_z", pa.float32()), ("right_eye_rot_w", pa.float32()),
            
            # 6. Validity Flags (2.46 - 2.49)
            ("hmd_tracking_valid", pa.float32()),
            ("left_tracking_valid", pa.float32()),
            ("right_tracking_valid", pa.float32()),
            ("eye_tracking_valid", pa.float32()),
            
            # 7. Biometrics (2.50 - 2.52)
            ("left_pupil_size", pa.float32()), ("right_pupil_size", pa.float32()), ("heart_rate_bpm", pa.float32()),
            
            # 8. Environment & System State (2.53 - 2.64)
            ("distance_to_boundary", pa.float32()), 
            ("app_fps", pa.float32()), 
            ("event_marker", pa.float32()),
            ("battery_hmd", pa.float32()), ("battery_left", pa.float32()), ("battery_right", pa.float32()),
            ("haptic_left_intensity", pa.float32()), ("haptic_right_intensity", pa.float32()),
            ("gaze_focal_distance", pa.float32()), 
            ("voice_amplitude_db", pa.float32()),
            ("cpu_utilization", pa.float32()), ("gpu_utilization", pa.float32()),
            
            # 9. Virtual Environment State (7.1 - 7.6)
            ("scene_id", pa.float32()),
            ("target_obj_pos_x", pa.float32()), ("target_obj_pos_y", pa.float32()), ("target_obj_pos_z", pa.float32()),
            ("dist_to_target_left", pa.float32()), ("dist_to_target_right", pa.float32())
        ])

    def start(self) -> None:
        """Initializes the Parquet binary file stream and readies the ingestion buffers."""
        try:
            self.writer = pq.ParquetWriter(
                str(self.output_path), 
                self._schema, 
                compression='snappy',
                use_dictionary=False
            )
            self.is_running = True
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

        with self._lock:
            # We directly append the pre-rendered tuple passed from the queue
            self.buffer.append(frame_tuple)
            
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
            # Transpose rows into columns for Arrow ingestion
            columns = list(zip(*self.buffer))
            
            arrays = [
                pa.array(columns[i], type=field.type)
                for i, field in enumerate(self._schema)
            ]
            
            batch = pa.RecordBatch.from_arrays(arrays, schema=self._schema)
            table = pa.Table.from_batches([batch])
            self.writer.write_table(table)
            
            self.buffer.clear()
        except Exception as e:
            logger.error(f"Critical disk write failure during Parquet flush: {e}")

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