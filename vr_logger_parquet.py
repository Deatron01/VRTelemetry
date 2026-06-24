import time
import queue
import threading
import os
import json
import uuid
from datetime import datetime, timezone
import pyarrow as pa
import pyarrow.parquet as pq
import xr  # pyopenxr
import psutil
import soundcard as sc
import numpy as np

class HighPerfVRLogger:
    def __init__(self):
        self.is_recording = False
        self.data_queue = queue.Queue(maxsize=20000) # Több mint 3 percnyi puffer 90Hz-en
        self.writer_thread = None
        self.session_dir = None
        self.parquet_file = None
        self.target_hz = 90
        
        # OpenXR alapok
        self.instance = None
        self.session = None
        self.system_id = None
        self.space_stage = None
        self.actions = {}
        self.spaces = {}

        # ==========================================
        # A 64-DIMENZIÓS NYERS ADATMODELL SÉMÁJA (III. Táblázat)
        # ==========================================
        self.schema = pa.schema([
            ('frame_index', pa.int64()), ('timestamp_ns', pa.int64()),
            
            # HMD (7)
            ('hmd_pos_x', pa.float32()), ('hmd_pos_y', pa.float32()), ('hmd_pos_z', pa.float32()),
            ('hmd_rot_x', pa.float32()), ('hmd_rot_y', pa.float32()), ('hmd_rot_z', pa.float32()), ('hmd_rot_w', pa.float32()),
            
            # Bal Kontroller (11)
            ('left_pos_x', pa.float32()), ('left_pos_y', pa.float32()), ('left_pos_z', pa.float32()),
            ('left_rot_x', pa.float32()), ('left_rot_y', pa.float32()), ('left_rot_z', pa.float32()), ('left_rot_w', pa.float32()),
            ('left_trigger', pa.float32()), ('left_grip', pa.float32()), ('left_joy_x', pa.float32()), ('left_joy_y', pa.float32()),
            
            # Jobb Kontroller (11)
            ('right_pos_x', pa.float32()), ('right_pos_y', pa.float32()), ('right_pos_z', pa.float32()),
            ('right_rot_x', pa.float32()), ('right_rot_y', pa.float32()), ('right_rot_z', pa.float32()), ('right_rot_w', pa.float32()),
            ('right_trigger', pa.float32()), ('right_grip', pa.float32()), ('right_joy_x', pa.float32()), ('right_joy_y', pa.float32()),
            
            # Bal Szem (7)
            ('left_eye_pos_x', pa.float32()), ('left_eye_pos_y', pa.float32()), ('left_eye_pos_z', pa.float32()),
            ('left_eye_rot_x', pa.float32()), ('left_eye_rot_y', pa.float32()), ('left_eye_rot_z', pa.float32()), ('left_eye_rot_w', pa.float32()),
            
            # Jobb Szem (7)
            ('right_eye_pos_x', pa.float32()), ('right_eye_pos_y', pa.float32()), ('right_eye_pos_z', pa.float32()),
            ('right_eye_rot_x', pa.float32()), ('right_eye_rot_y', pa.float32()), ('right_eye_rot_z', pa.float32()), ('right_eye_rot_w', pa.float32()),
            
            # Adatminőség / Tracking Valid (4)
            ('hmd_tracking_valid', pa.float32()), ('left_tracking_valid', pa.float32()), 
            ('right_tracking_valid', pa.float32()), ('eye_tracking_valid', pa.float32()),
            
            # Biometria (3)
            ('left_pupil_size', pa.float32()), ('right_pupil_size', pa.float32()), ('heart_rate_bpm', pa.float32()),
            
            # Kontextus (3)
            ('distance_to_boundary', pa.float32()), ('app_fps', pa.float32()), ('event_marker', pa.float32()),
            
            # Rendszer (3)
            ('battery_hmd', pa.float32()), ('battery_left', pa.float32()), ('battery_right', pa.float32()),
            
            # Extra AI Feature-ök (6)
            ('haptic_left_intensity', pa.float32()), ('haptic_right_intensity', pa.float32()), 
            ('gaze_focal_distance', pa.float32()), ('voice_amplitude_db', pa.float32()), 
            ('cpu_utilization', pa.float32()), ('gpu_utilization', pa.float32())
        ])

    def generate_static_metadata(self):
        """Kigenerálja a IV. és V. táblázat alapjait a mérés indításakor."""
        # Megpróbáljuk lekérni a VR hardver nevét, ha inicializálva van
        hmd_name = "Ismeretlen HMD"
        if self.instance:
            props = xr.get_system_properties(self.instance, self.system_id)
            hmd_name = props.system_name

        metadata = {
            "session_info": {
                "session_id": str(uuid.uuid4()),
                "start_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "target_hz": self.target_hz,
                "tracking_space_type": "STAGE"
            },
            "subject_profile": {
                "subject_id": "SUBJ_DEFAULT",
                "height_cm": 184.0,  # Ezeket UI-ról lehet majd bekérni
                "weight_kg": 115.0,
                "dominant_hand": "Right"
            },
            "hardware_profile": {
                "host_os_version": f"{os.name} {os.environ.get('OS','')}",
                "host_cpu_model": "Pre-configured CPU", # WMI/Registry lekérdezés helye
                "host_ram_gb": round(psutil.virtual_memory().total / (1024**3)),
                "hmd_model": hmd_name,
                "has_eye_tracking": True
            }
        }
        
        meta_path = os.path.join(self.session_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)
        print(f"[*] Metaadatok elmentve: {meta_path}")

    def start_recording(self, session_dir, target_hz=90):
        self.session_dir = session_dir
        os.makedirs(self.session_dir, exist_ok=True)
        self.parquet_file = os.path.join(self.session_dir, "telemetry_raw.parquet")
        self.target_hz = target_hz
        
        # Metaadatok rögzítése
        self.generate_static_metadata()
        
        while not self.data_queue.empty(): self.data_queue.get()
        self.is_recording = True
        
        self.writer_thread = threading.Thread(target=self._parquet_writer_loop, daemon=True)
        self.writer_thread.start()
        threading.Thread(target=self._openxr_reader_loop, daemon=True).start()
        
        print(f"🚀 AI-Kész VR Rögzítés indítva (Nyers Mód, {self.target_hz}Hz).")

    def stop_recording(self):
        self.is_recording = False
        print("⏳ Leállítás... Pufferelt adatok kiírása az SSD-re...")
        if self.writer_thread:
            self.writer_thread.join()
        print("✅ Felvétel biztonságosan lezárva. Adatvesztés: 0%")

    def _openxr_reader_loop(self):
        """A 90Hz-es Hot-Loop. Szigorúan 0 számítás, csak adatkinyerés és Queue-ba dobás."""
        frame_idx = 0
        TARGET_DT = 1.0 / self.target_hz
        
        # Audio setup a voice_amplitude_db-hez
        try:
            mic = sc.default_microphone()
        except:
            mic = None

        while self.is_recording:
            loop_start = time.perf_counter()
            current_time_ns = time.perf_counter_ns()
            
            # ----------------------------------------------------
            # IDE JÖN AZ OPENXR xr.wait_frame / xr.locate_space LOGIKA
            # Ezt a részt fogod rákötni a valódi HMD-dre.
            # ----------------------------------------------------
            
            # Szimulált Dummy Adatsor (Fallback, amíg a szemüveg nincs a fejeden)
            data_row = {
                'frame_index': frame_idx, 'timestamp_ns': current_time_ns,
                
                'hmd_pos_x': 0.0, 'hmd_pos_y': 1.6, 'hmd_pos_z': 0.0,
                'hmd_rot_x': 0.0, 'hmd_rot_y': 0.0, 'hmd_rot_z': 0.0, 'hmd_rot_w': 1.0,
                
                'left_pos_x': -0.2, 'left_pos_y': 1.0, 'left_pos_z': -0.3,
                'left_rot_x': 0.0, 'left_rot_y': 0.0, 'left_rot_z': 0.0, 'left_rot_w': 1.0,
                'left_trigger': 0.0, 'left_grip': 0.0, 'left_joy_x': 0.0, 'left_joy_y': 0.0,
                
                'right_pos_x': 0.2, 'right_pos_y': 1.0, 'right_pos_z': -0.3,
                'right_rot_x': 0.0, 'right_rot_y': 0.0, 'right_rot_z': 0.0, 'right_rot_w': 1.0,
                'right_trigger': 0.0, 'right_grip': 0.0, 'right_joy_x': 0.0, 'right_joy_y': 0.0,
                
                'left_eye_pos_x': 0.0, 'left_eye_pos_y': 0.0, 'left_eye_pos_z': 0.0,
                'left_eye_rot_x': 0.0, 'left_eye_rot_y': 0.0, 'left_eye_rot_z': 0.0, 'left_eye_rot_w': 1.0,
                
                'right_eye_pos_x': 0.0, 'right_eye_pos_y': 0.0, 'right_eye_pos_z': 0.0,
                'right_eye_rot_x': 0.0, 'right_eye_rot_y': 0.0, 'right_eye_rot_z': 0.0, 'right_eye_rot_w': 1.0,
                
                'hmd_tracking_valid': 1.0, 'left_tracking_valid': 1.0, 
                'right_tracking_valid': 1.0, 'eye_tracking_valid': 1.0,
                
                'left_pupil_size': 3.5, 'right_pupil_size': 3.5, 'heart_rate_bpm': 0.0,
                
                'distance_to_boundary': 2.5, 'app_fps': 90.0, 'event_marker': 0.0,
                
                'battery_hmd': 1.0, 'battery_left': 1.0, 'battery_right': 1.0,
                
                'haptic_left_intensity': 0.0, 'haptic_right_intensity': 0.0,
                'gaze_focal_distance': 2.0, 
                
                # Dinamikusan lekérdezett CPU terhelés (gyors, nem akasztja a loopot)
                'cpu_utilization': psutil.cpu_percent(), 
                'gpu_utilization': 0.0,
                'voice_amplitude_db': 0.0
            }
            
            self.data_queue.put(data_row)
            frame_idx += 1
            
            elapsed = time.perf_counter() - loop_start
            sleep_time = TARGET_DT - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _parquet_writer_loop(self):
        """Aszinkron batch-írás az SSD-re (Google Snappy tömörítéssel)."""
        writer = pq.ParquetWriter(self.parquet_file, self.schema, compression='snappy')
        batch = []
        BATCH_SIZE = self.target_hz * 3  # 3 másodperces blokkok

        while self.is_recording or not self.data_queue.empty():
            try:
                row = self.data_queue.get(timeout=0.1) 
                batch.append(row)
                
                if len(batch) >= BATCH_SIZE:
                    table = pa.Table.from_pylist(batch, schema=self.schema)
                    writer.write_table(table)
                    batch.clear() 
            except queue.Empty:
                continue
                
        if len(batch) > 0:
            table = pa.Table.from_pylist(batch, schema=self.schema)
            writer.write_table(table)
            
        writer.close()

# Példányosítás a globális hozzáféréshez (ahogy a szervered is használja)
vr_logger_instance = HighPerfVRLogger()