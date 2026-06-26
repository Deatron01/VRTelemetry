import threading
import queue
import time
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from src.core.datatypes import TelemetryFrame

class AsyncParquetWriter:
    """
    High-frequency I/O thread. 
    Batches TelemetryFrame tuples in memory and flushes to SSD asynchronously.
    """
    def __init__(self, output_path: Path, target_hz: int = 90, batch_seconds: int = 2):
        self.output_path = output_path
        self.target_hz = target_hz
        self.batch_size = target_hz * batch_seconds
        
        # We use a Queue size large enough to hold ~30 seconds of data 
        # in case the OS temporarily locks the disk during an anti-virus scan or spike.
        self.data_queue = queue.Queue(maxsize=target_hz * 30)
        self.is_running = False
        self.writer_thread = None
        self._writer = None

        # Schema mapping directly to TelemetryFrame.to_tuple()
        self.schema = pa.schema([
            ('frame_index', pa.int64()), ('timestamp_ns', pa.int64()),
            ('hmd_pos_x', pa.float32()), ('hmd_pos_y', pa.float32()), ('hmd_pos_z', pa.float32()),
            ('hmd_rot_x', pa.float32()), ('hmd_rot_y', pa.float32()), ('hmd_rot_z', pa.float32()), ('hmd_rot_w', pa.float32()),
            ('hmd_tracking_valid', pa.float32()),
            ('left_pos_x', pa.float32()), ('left_pos_y', pa.float32()), ('left_pos_z', pa.float32()),
            ('left_rot_x', pa.float32()), ('left_rot_y', pa.float32()), ('left_rot_z', pa.float32()), ('left_rot_w', pa.float32()),
            ('left_trigger', pa.float32()), ('left_grip', pa.float32()), ('left_joy_x', pa.float32()), ('left_joy_y', pa.float32()),
            ('left_tracking_valid', pa.float32()),
            ('right_pos_x', pa.float32()), ('right_pos_y', pa.float32()), ('right_pos_z', pa.float32()),
            ('right_rot_x', pa.float32()), ('right_rot_y', pa.float32()), ('right_rot_z', pa.float32()), ('right_rot_w', pa.float32()),
            ('right_trigger', pa.float32()), ('right_grip', pa.float32()), ('right_joy_x', pa.float32()), ('right_joy_y', pa.float32()),
            ('right_tracking_valid', pa.float32()),
            ('left_eye_pos_x', pa.float32()), ('left_eye_pos_y', pa.float32()), ('left_eye_pos_z', pa.float32()),
            ('left_eye_rot_x', pa.float32()), ('left_eye_rot_y', pa.float32()), ('left_eye_rot_z', pa.float32()), ('left_eye_rot_w', pa.float32()),
            ('right_eye_pos_x', pa.float32()), ('right_eye_pos_y', pa.float32()), ('right_eye_pos_z', pa.float32()),
            ('right_eye_rot_x', pa.float32()), ('right_eye_rot_y', pa.float32()), ('right_eye_rot_z', pa.float32()), ('right_eye_rot_w', pa.float32()),
            ('eye_tracking_valid', pa.float32()),
            ('left_pupil_size', pa.float32()), ('right_pupil_size', pa.float32()), ('heart_rate_bpm', pa.float32()),
            ('cpu_utilization', pa.float32()), ('gpu_utilization', pa.float32()),
            ('battery_hmd', pa.float32()), ('battery_left', pa.float32()), ('battery_right', pa.float32())
        ])

    def start(self) -> None:
        self.is_running = True
        self._writer = pq.ParquetWriter(self.output_path, self.schema, compression='snappy')
        self.writer_thread = threading.Thread(target=self._io_loop, daemon=True)
        self.writer_thread.start()

    def push(self, frame: TelemetryFrame) -> None:
        try:
            # Non-blocking put. If the queue is full, the OS is severely failing disk I/O.
            self.data_queue.put_nowait(frame.to_tuple())
        except queue.Full:
            print("[!] CRITICAL: I/O Buffer overflow. Disk is too slow. Dropping frame.")

    def _io_loop(self) -> None:
        batch = []
        while self.is_running or not self.data_queue.empty():
            try:
                # Wait up to 50ms for a frame
                row = self.data_queue.get(timeout=0.05)
                batch.append(row)
                
                # Flush to disk when batch is full
                if len(batch) >= self.batch_size:
                    self._flush_batch(batch)
                    batch.clear()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[!] Storage Exception: {e}")

        # Final flush on shutdown
        if batch:
            self._flush_batch(batch)
        if self._writer:
            self._writer.close()

    def _flush_batch(self, batch: list) -> None:
        # Constructing PyArrow Table from pylist is highly optimized
        table = pa.Table.from_pylist([dict(zip(self.schema.names, r)) for r in batch], schema=self.schema)
        self._writer.write_table(table)

    def stop(self) -> None:
        self.is_running = False
        if self.writer_thread:
            self.writer_thread.join(timeout=5.0)