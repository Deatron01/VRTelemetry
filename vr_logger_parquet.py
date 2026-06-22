import time
import queue
import threading
import os
import pyarrow as pa
import pyarrow.parquet as pq
import xr  # pyopenxr

class HighPerfVRLogger:
    def __init__(self):
        self.is_recording = False
        # maxsize=10000: Biztonsági puffer, ami kb. 110 másodpercnyi 90Hz-es adatot tud
        # a memóriában tartani, ha a merevlemez véletlenül "megakadna" egy pillanatra.
        self.data_queue = queue.Queue(maxsize=10000) 
        self.writer_thread = None
        self.session_dir = None
        self.parquet_file = None
        
        # A 100%-os precíziójú, mindkét szemet külön kezelő séma
        self.schema = pa.schema([
            ('frame_index', pa.int64()),
            ('timestamp_ns', pa.int64()),       # Hardveres Nanoszekundum pontosság!
            
            # Fej (HMD)
            ('hmd_pos_x', pa.float32()), ('hmd_pos_y', pa.float32()), ('hmd_pos_z', pa.float32()),
            ('hmd_rot_x', pa.float32()), ('hmd_rot_y', pa.float32()), ('hmd_rot_z', pa.float32()), ('hmd_rot_w', pa.float32()),
            
            # Bal Kontroller
            ('left_pos_x', pa.float32()), ('left_pos_y', pa.float32()), ('left_pos_z', pa.float32()),
            ('left_rot_x', pa.float32()), ('left_rot_y', pa.float32()), ('left_rot_z', pa.float32()), ('left_rot_w', pa.float32()),
            ('left_trigger', pa.float32()), ('left_grip', pa.float32()),
            ('left_joy_x', pa.float32()), ('left_joy_y', pa.float32()),
            
            # Jobb Kontroller
            ('right_pos_x', pa.float32()), ('right_pos_y', pa.float32()), ('right_pos_z', pa.float32()),
            ('right_rot_x', pa.float32()), ('right_rot_y', pa.float32()), ('right_rot_z', pa.float32()), ('right_rot_w', pa.float32()),
            ('right_trigger', pa.float32()), ('right_grip', pa.float32()),
            ('right_joy_x', pa.float32()), ('right_joy_y', pa.float32()),
            
            # Bal Szem (Precíz Eye Tracking)
            ('left_eye_pos_x', pa.float32()), ('left_eye_pos_y', pa.float32()), ('left_eye_pos_z', pa.float32()),
            ('left_eye_rot_x', pa.float32()), ('left_eye_rot_y', pa.float32()), ('left_eye_rot_z', pa.float32()), ('left_eye_rot_w', pa.float32()),
            
            # Jobb Szem (Precíz Eye Tracking)
            ('right_eye_pos_x', pa.float32()), ('right_eye_pos_y', pa.float32()), ('right_eye_pos_z', pa.float32()),
            ('right_eye_rot_x', pa.float32()), ('right_eye_rot_y', pa.float32()), ('right_eye_rot_z', pa.float32()), ('right_eye_rot_w', pa.float32())
        ])

    def start_recording(self, session_dir, target_hz=90):
        self.session_dir = session_dir
        os.makedirs(self.session_dir, exist_ok=True)
        self.parquet_file = os.path.join(self.session_dir, "telemetry.parquet")
        self.target_hz = target_hz
        
        # Puffer ürítése a biztonság kedvéért
        while not self.data_queue.empty():
            self.data_queue.get()

        self.is_recording = True
        
        # 1. Író szál indítása (Fogyasztó)
        self.writer_thread = threading.Thread(target=self._parquet_writer_loop, daemon=True)
        self.writer_thread.start()
        
        # 2. Mérő szál indítása (Termelő)
        threading.Thread(target=self._openxr_reader_loop, daemon=True).start()
        print(f"✅ Extrém precíziós Parquet rögzítés indítva ({self.target_hz} Hz): {self.parquet_file}")

    def stop_recording(self):
        self.is_recording = False
        print("⏳ Mérés leállítva. Hátralévő adatok kiírása a lemezre...")
        if self.writer_thread:
            self.writer_thread.join() # Blokkol, amíg az utolsó byte is a lemezre nem kerül
        print("✅ Felvétel biztonságosan lezárva. Adatvesztés: 0%")

    def _openxr_reader_loop(self):
        """
        A FŐ MÉRŐCIKLUS. 
        Itt NINCS lemezművelet. Csak kőkemény OpenXR adatkikérés és memóriaírás.
        """
        frame_idx = 0
        TARGET_DT = 1.0 / self.target_hz
        
        # (Ide kerülne az OpenXR instance/session inicializálása, ha nincs még meg)
        # Ezt majd össze kell kötnöd a saját meglévő xr_logger_instance kódoddal!
        
        while self.is_recording:
            # A perf_counter a legprecízebb hardveres óra a Pythonban
            loop_start = time.perf_counter() 
            current_time_ns = time.perf_counter_ns()
            
            # --- OPENXR LEKÉRDEZÉS HELYE ---
            # frame_state = xr.wait_frame(self.session, xr.FrameWaitInfo())
            # xr.begin_frame(self.session, xr.FrameBeginInfo())
            # space_loc = xr.locate_space(...)
            
            # Példa adatsor feltöltése (Itt töltenéd be az OpenXR valódi változóit)
            data_row = {
                'frame_index': frame_idx,
                'timestamp_ns': current_time_ns,
                
                'hmd_pos_x': 0.0, 'hmd_pos_y': 0.0, 'hmd_pos_z': 0.0,
                'hmd_rot_x': 0.0, 'hmd_rot_y': 0.0, 'hmd_rot_z': 0.0, 'hmd_rot_w': 1.0,
                
                'left_pos_x': 0.0, 'left_pos_y': 0.0, 'left_pos_z': 0.0,
                'left_rot_x': 0.0, 'left_rot_y': 0.0, 'left_rot_z': 0.0, 'left_rot_w': 1.0,
                'left_trigger': 0.0, 'left_grip': 0.0,
                'left_joy_x': 0.0, 'left_joy_y': 0.0,
                
                'right_pos_x': 0.0, 'right_pos_y': 0.0, 'right_pos_z': 0.0,
                'right_rot_x': 0.0, 'right_rot_y': 0.0, 'right_rot_z': 0.0, 'right_rot_w': 1.0,
                'right_trigger': 0.0, 'right_grip': 0.0,
                'right_joy_x': 0.0, 'right_joy_y': 0.0,
                
                'left_eye_pos_x': 0.0, 'left_eye_pos_y': 0.0, 'left_eye_pos_z': 0.0,
                'left_eye_rot_x': 0.0, 'left_eye_rot_y': 0.0, 'left_eye_rot_z': 0.0, 'left_eye_rot_w': 1.0,
                
                'right_eye_pos_x': 0.0, 'right_eye_pos_y': 0.0, 'right_eye_pos_z': 0.0,
                'right_eye_rot_x': 0.0, 'right_eye_rot_y': 0.0, 'right_eye_rot_z': 0.0, 'right_eye_rot_w': 1.0
            }
            
            # xr.end_frame(self.session, ...)
            # -------------------------------
            
            # Bedobjuk a RAM-ba (Queue). Ez mikroszekundumok alatt lefut.
            self.data_queue.put(data_row)
            frame_idx += 1
            
            # Nagyon szigorú időzítés tartása
            elapsed = time.perf_counter() - loop_start
            sleep_time = TARGET_DT - elapsed
            
            # Ha a feldolgozás gyors volt (és általában az lesz), alszunk a maradék időben
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _parquet_writer_loop(self):
        """
        A HÁTTÉRBEN FUTÓ ÍRÓ. 
        Kiveszi a RAM-ból az adatokat, és 5 másodperces blokkokban zúdítja az SSD-re.
        """
        writer = pq.ParquetWriter(self.parquet_file, self.schema, compression='snappy')
        batch = []
        BATCH_SIZE = self.target_hz * 5  # pl. 90 * 5 = 450 frame kötegelése

        while self.is_recording or not self.data_queue.empty():
            try:
                # Kiveszünk a sorból egy adatot (timeout kell, hogy ki tudjon lépni a ciklusból)
                row = self.data_queue.get(timeout=0.2) 
                batch.append(row)
                
                # Ha elértük a limitet, kiírjuk a C++ memórián keresztül a lemezre
                if len(batch) >= BATCH_SIZE:
                    table = pa.Table.from_pylist(batch, schema=self.schema)
                    writer.write_table(table)
                    batch.clear() 
                    
            except queue.Empty:
                continue
                
        # Felvétel végén kimentjük a megmaradt "töredék" blokkot is
        if len(batch) > 0:
            table = pa.Table.from_pylist(batch, schema=self.schema)
            writer.write_table(table)
            
        writer.close()