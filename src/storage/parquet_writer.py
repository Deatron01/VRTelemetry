import queue
import threading
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from src.core.datatypes import TelemetryFrame

class AsyncParquetWriter:
    """
    Thread-isolated columnar Parquet storage subsystem. Performs disk flushing
    asynchronously using Snappy compression block formats.
    """
    def __init__(self, output_path: Path, target_hz: int = 90):
        self.output_path = output_path
        self.batch_size = target_hz * 3
        self.data_queue = queue.Queue(maxsize=target_hz * 60)
        self.is_running = False
        self._thread = None
        self._writer = None

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
            ('distance_to_boundary', pa.float32()), ('app_fps', pa.float32()), ('event_marker', pa.float32()),
            ('battery_hmd', pa.float32()), ('battery_left', pa.float32()), ('battery_right', pa.float32()),
            ('haptic_left_intensity', pa.float32()), ('haptic_right_intensity', pa.float32()),
            ('gaze_focal_distance', pa.float32()), ('voice_amplitude_db', pa.float32()),
            ('cpu_utilization', pa.float32()), ('gpu_utilization', pa.float32())
        ])

    def start(self) -> None:
        self.is_running = True
        self._writer = pq.ParquetWriter(self.output_path, self.schema, compression='snappy')
        self._thread = threading.Thread(target=self._io_loop, daemon=True)
        self._thread.start()

    def push(self, frame: TelemetryFrame) -> None:
        try:
            self.data_queue.put_nowait(frame.to_tuple())
        except queue.Full:
            pass # Non-blocking behavior handles queue issues gracefully under severe storage stress

    def _io_loop(self) -> None:
        batch = []
        while self.is_running or not self.data_queue.empty():
            try:
                row = self.data_queue.get(timeout=0.05)
                batch.append(row)
                if len(batch) >= self.batch_size:
                    self._flush(batch)
                    batch.clear()
            except queue.Empty:
                if batch and not self.is_running:
                    self._flush(batch)
                    batch.clear()

        if batch:
            self._flush(batch)
        if self._writer:
            self._writer.close()

    def _flush(self, batch: list) -> None:
        # Resolves internal tuples directly to memory-mapped columnar tables
        dict_batch = {name: [row[i] for row in batch] for i, name in enumerate(self.schema.names)}
        table = pa.Table.from_pydict(dict_batch, schema=self.schema)
        self._writer.write_table(table)

    def stop(self) -> None:
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=5.0)