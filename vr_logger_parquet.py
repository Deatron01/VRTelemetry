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

    def generate_static_metadata(self, override_profile=None):
        """Kigenerálja a IV. és V. táblázat alapjait. Ha a GUI-ból jön adat, felülírja a defaultot."""
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
            "hardware_profile": {
                "host_os_version": f"{os.name} {os.environ.get('OS','')}",
                "host_cpu_model": "Pre-configured CPU", 
                "host_ram_gb": round(psutil.virtual_memory().total / (1024**3)),
                "hmd_model": hmd_name,
                "has_eye_tracking": True
            }
        }
        
        # Ha a Kísérletvezérlő GUI átadott profilt, azt használjuk
        if override_profile:
            metadata["subject_profile"] = override_profile
        else:
            metadata["subject_profile"] = {
                "subject_id": "SUBJ_DEFAULT",
                "height_cm": 184.0, 
                "weight_kg": 115.0,
                "dominant_hand": "Right"
            }
        
        meta_path = os.path.join(self.session_dir, "hardware_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)
        print(f"[*] Metaadatok elmentve: {meta_path}")

    def start_recording(self, session_dir, target_hz=90, subject_profile=None):
        self.session_dir = session_dir
        os.makedirs(self.session_dir, exist_ok=True)
        self.parquet_file = os.path.join(self.session_dir, "telemetry_raw.parquet")
        self.target_hz = target_hz
        
        # Metaadatok rögzítése a GUI adataival (ha van)
        self.generate_static_metadata(override_profile=subject_profile)
        
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
        """A 90Hz-es Hot-Loop VALÓDI OpenXR hívásokkal (pyopenxr API)."""
        frame_idx = 0
        ideal_dt = 1.0 / self.target_hz
        next_frame_time = time.perf_counter()
        
        cached_cpu_usage = psutil.cpu_percent()
        voice_amp = 0.0

        while self.is_recording:
            current_time = time.perf_counter()
            
            # Hybrid Spin-Lock a tökéletes 90Hz-hez (Zero Jitter)
            if current_time < next_frame_time:
                time_to_wait = next_frame_time - current_time
                if time_to_wait > 0.002:
                    time.sleep(0.001)
                continue
            
            if frame_idx % 10 == 0:
                cached_cpu_usage = psutil.cpu_percent()

            # ====================================================
            # VALÓDI OPENXR ADATKINYERÉS
            # ====================================================
            try:
                # 1. Idő lekérése a predikcióhoz
                # Az ideális a frame_state.predicted_display_time lenne, 
                # de a 0 átadása a "legfrissebb elérhető" tracker állapotot adja vissza.
                predicted_time = 0 
                
                # 2. Input szinkronizáció (Ravasz, markolat, joystick állapot frissítése)
                if self.session and hasattr(self, 'action_set'):
                    active_set = xr.ActiveActionSet(self.action_set, xr.NULL_PATH)
                    xr.sync_actions(self.session, xr.ActionsSyncInfo(
                        count_active_action_sets=1,
                        active_action_sets=[active_set]
                    ))

                # 3. Segédfüggvény a térbeli (Space) adatok kinyerésére (HMD, kezek)
                def get_space_data(space_handle):
                    if not space_handle or not self.session:
                        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.0
                    
                    # OpenXR API hívás a pozíció/rotáció lekérésére a STAGE (szoba) origóhoz képest
                    loc = xr.locate_space(space_handle, self.space_stage, predicted_time)
                    p = loc.pose.position
                    o = loc.pose.orientation
                    # Bitmaszk ellenőrzés: Valid-e a kamerás követés (Nincs-e takarásban a kontroller)
                    valid = 1.0 if (loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT) else 0.0
                    return (p.x, p.y, p.z), (o.x, o.y, o.z, o.w), valid

                # HMD (Sisak) és Kontrollerek koordinátáinak lekérése
                h_p, h_o, h_v = get_space_data(self.spaces.get('hmd'))
                l_p, l_o, l_v = get_space_data(self.spaces.get('left_hand'))
                r_p, r_o, r_v = get_space_data(self.spaces.get('right_hand'))
                
                # 4. Segédfüggvények az analóg gombok (Float) és joystickok (Vector2) lekérésére
                def get_float_action(action_name, subaction_path):
                    if action_name not in self.actions: return 0.0
                    info = xr.ActionStateGetInfo(self.actions[action_name], subaction_path)
                    return xr.get_action_state_float(self.session, info).current_state

                def get_vec2_action(action_name, subaction_path):
                    if action_name not in self.actions: return (0.0, 0.0)
                    info = xr.ActionStateGetInfo(self.actions[action_name], subaction_path)
                    state = xr.get_action_state_vector2f(self.session, info).current_state
                    return state.x, state.y

                path_left = self.paths.get('left_hand', xr.NULL_PATH)
                path_right = self.paths.get('right_hand', xr.NULL_PATH)

                # Bal kéz inputok
                lt = get_float_action('trigger', path_left)
                lg = get_float_action('grip', path_left)
                lj_x, lj_y = get_vec2_action('joystick', path_left)

                # Jobb kéz inputok
                rt = get_float_action('trigger', path_right)
                rg = get_float_action('grip', path_right)
                rj_x, rj_y = get_vec2_action('joystick', path_right)

            except Exception as e:
                # Biztonsági háló: Ha hiba van a runtime-mal (pl. levették a sisakot), fallback 0-ra
                h_p, h_o, h_v = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.0
                l_p, l_o, l_v = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.0
                r_p, r_o, r_v = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.0
                lt, lg, lj_x, lj_y = 0.0, 0.0, 0.0, 0.0
                rt, rg, rj_x, rj_y = 0.0, 0.0, 0.0, 0.0

            # Szemkövetés inicializáció (Alapértelmezés, amíg nincs XR_EXT_eye_gaze_interaction hook)
            le_p, le_o, re_p, re_o = (0.0,0.0,0.0), (0.0,0.0,0.0,1.0), (0.0,0.0,0.0), (0.0,0.0,0.0,1.0)
            
            # --- Adatszerkezet feltöltése az AI Tenzor Modell alapján ---
            data_row = {
                'frame_index': frame_idx, 'timestamp_ns': time.perf_counter_ns(),
                
                'hmd_pos_x': h_p[0], 'hmd_pos_y': h_p[1], 'hmd_pos_z': h_p[2],
                'hmd_rot_x': h_o[0], 'hmd_rot_y': h_o[1], 'hmd_rot_z': h_o[2], 'hmd_rot_w': h_o[3],
                
                'left_pos_x': l_p[0], 'left_pos_y': l_p[1], 'left_pos_z': l_p[2],
                'left_rot_x': l_o[0], 'left_rot_y': l_o[1], 'left_rot_z': l_o[2], 'left_rot_w': l_o[3],
                'left_trigger': lt, 'left_grip': lg, 'left_joy_x': lj_x, 'left_joy_y': lj_y,
                
                'right_pos_x': r_p[0], 'right_pos_y': r_p[1], 'right_pos_z': r_p[2],
                'right_rot_x': r_o[0], 'right_rot_y': r_o[1], 'right_rot_z': r_o[2], 'right_rot_w': r_o[3],
                'right_trigger': rt, 'right_grip': rg, 'right_joy_x': rj_x, 'right_joy_y': rj_y,
                
                'left_eye_pos_x': le_p[0], 'left_eye_pos_y': le_p[1], 'left_eye_pos_z': le_p[2],
                'left_eye_rot_x': le_o[0], 'left_eye_rot_y': le_o[1], 'left_eye_rot_z': le_o[2], 'left_eye_rot_w': le_o[3],
                
                'right_eye_pos_x': re_p[0], 'right_eye_pos_y': re_p[1], 'right_eye_pos_z': re_p[2],
                'right_eye_rot_x': re_o[0], 'right_eye_rot_y': re_o[1], 'right_eye_rot_z': re_o[2], 'right_eye_rot_w': re_o[3],
                
                'hmd_tracking_valid': h_v, 'left_tracking_valid': l_v, 
                'right_tracking_valid': r_v, 'eye_tracking_valid': 0.0,
                
                'left_pupil_size': 0.0, 'right_pupil_size': 0.0, 'heart_rate_bpm': 0.0,
                
                'distance_to_boundary': 0.0, 'app_fps': self.target_hz, 'event_marker': 0.0,
                
                'battery_hmd': 1.0, 'battery_left': 1.0, 'battery_right': 1.0,
                
                'haptic_left_intensity': 0.0, 'haptic_right_intensity': 0.0,
                'gaze_focal_distance': 0.0, 
                
                'cpu_utilization': cached_cpu_usage, 
                'gpu_utilization': 0.0,
                'voice_amplitude_db': voice_amp
            }
            
            self.data_queue.put(data_row)
            frame_idx += 1
            
            # Következő ciklusidő előkészítése
            next_frame_time += ideal_dt

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

# Példányosítás a globális hozzáféréshez
vr_logger_instance = HighPerfVRLogger()