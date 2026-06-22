import time
import queue
import threading
import os
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

# ==========================================
# 1. TUDOMÁNYOS ADATSTRUKTÚRA (SCHEMA)
# ==========================================
# Ez garantálja a típusbiztonságot, a minimális memóriahasználatot (float32) 
# és a villámgyors bináris kimentést.
VR_TELEMETRY_SCHEMA = pa.schema([
    ('frame_index', pa.int64()),
    ('timestamp_ns', pa.int64()),       # Hardveres óra (Nanoszekundum)
    
    ('hmd_pos_x', pa.float32()), ('hmd_pos_y', pa.float32()), ('hmd_pos_z', pa.float32()),
    ('hmd_rot_x', pa.float32()), ('hmd_rot_y', pa.float32()), ('hmd_rot_z', pa.float32()), ('hmd_rot_w', pa.float32()),
    
    ('left_pos_x', pa.float32()), ('left_pos_y', pa.float32()), ('left_pos_z', pa.float32()),
    ('left_rot_x', pa.float32()), ('left_rot_y', pa.float32()), ('left_rot_z', pa.float32()), ('left_rot_w', pa.float32()),
    ('left_trigger', pa.float32()), ('left_grip', pa.float32()),
    
    ('right_pos_x', pa.float32()), ('right_pos_y', pa.float32()), ('right_pos_z', pa.float32()),
    ('right_rot_x', pa.float32()), ('right_rot_y', pa.float32()), ('right_rot_z', pa.float32()), ('right_rot_w', pa.float32()),
    ('right_trigger', pa.float32()), ('right_grip', pa.float32()),
    
    ('left_eye_pos_x', pa.float32()), ('left_eye_pos_y', pa.float32()), ('left_eye_pos_z', pa.float32()),
    ('left_eye_rot_x', pa.float32()), ('left_eye_rot_y', pa.float32()), ('left_eye_rot_z', pa.float32()), ('left_eye_rot_w', pa.float32()),
    
    ('right_eye_pos_x', pa.float32()), ('right_eye_pos_y', pa.float32()), ('right_eye_pos_z', pa.float32()),
    ('right_eye_rot_x', pa.float32()), ('right_eye_rot_y', pa.float32()), ('right_eye_rot_z', pa.float32()), ('right_eye_rot_w', pa.float32())
])

class VRLossAnalyzerTest:
    def __init__(self, target_hz=90, duration_sec=10):
        self.target_hz = target_hz
        self.duration_sec = duration_sec
        self.is_running = False
        self.data_queue = queue.Queue(maxsize=10000)
        self.output_file = "scientific_test_telemetry.parquet"
        self.frames_generated = 0
        
    # ==========================================
    # 2. ELŐÁLLÍTÓ EGYSÉG (Szimulált OpenXR)
    # ==========================================
    def _mock_openxr_producer(self):
        """Precíziós hardveres időzítővel szimulálja a 90 Hz-es VR szenzorokat."""
        ideal_dt = 1.0 / self.target_hz
        next_frame_time = time.perf_counter()
        
        while self.is_running:
            current_time = time.perf_counter()
            
            # Megvárjuk a tökéletes időpontot a következő frame-hez (Spin-lock a max precízióért)
            if current_time < next_frame_time:
                continue 
                
            # Adatszerkezet feltöltése
            data_row = {
                'frame_index': self.frames_generated,
                'timestamp_ns': time.perf_counter_ns(), # Nanosec precízió
                
                'hmd_pos_x': 0.1, 'hmd_pos_y': 1.6, 'hmd_pos_z': -0.2,
                'hmd_rot_x': 0.01, 'hmd_rot_y': 1.01, 'hmd_rot_z': 01.10, 'hmd_rot_w': 0.01,
                
                'left_pos_x': -0.2, 'left_pos_y': 1.2, 'left_pos_z': -0.4,
                'left_rot_x': 0.01, 'left_rot_y': 0.01, 'left_rot_z': 0.01, 'left_rot_w': 1.10,
                'left_trigger': 0.51, 'left_grip': 0.01,
                
                'right_pos_x': 0.2, 'right_pos_y': 1.2, 'right_pos_z': -0.4,
                'right_rot_x': 0.01, 'right_rot_y': 0.01, 'right_rot_z': 0.01, 'right_rot_w': 1.01,
                'right_trigger': 0.01, 'right_grip': 0.8,
                
                'left_eye_pos_x': -0.03, 'left_eye_pos_y': 0.01, 'left_eye_pos_z': 0.01,
                'left_eye_rot_x': 0.01, 'left_eye_rot_y': 0.01, 'left_eye_rot_z': 0.01, 'left_eye_rot_w': 1.01,
                
                'right_eye_pos_x': 0.03, 'right_eye_pos_y': 0.01, 'right_eye_pos_z': 0.01,
                'right_eye_rot_x': 0.01, 'right_eye_rot_y': 0.01, 'right_eye_rot_z': 0.01, 'right_eye_rot_w': 1.01
            }
            
            # Memóriába dobás (Azonnali I/O blokkolás nélkül)
            self.data_queue.put(data_row)
            self.frames_generated += 1
            next_frame_time += ideal_dt

    # ==========================================
    # 3. MENTŐ EGYSÉG (Háttér Parquet Író)
    # ==========================================
    def _parquet_consumer(self):
        """Aszinkron írja a lemezre a queue tartalmát anélkül, hogy a producernél frame drop-ot okozna."""
        writer = pq.ParquetWriter(self.output_file, VR_TELEMETRY_SCHEMA, compression='snappy')
        batch = []
        batch_size = self.target_hz * 2  # 2 másodpercenkénti kötegelt írás a lemezre
        
        while self.is_running or not self.data_queue.empty():
            try:
                row = self.data_queue.get(timeout=0.1)
                batch.append(row)
                
                if len(batch) >= batch_size:
                    table = pa.Table.from_pylist(batch, schema=VR_TELEMETRY_SCHEMA)
                    writer.write_table(table)
                    batch.clear()
            except queue.Empty:
                continue
                
        if len(batch) > 0:
            table = pa.Table.from_pylist(batch, schema=VR_TELEMETRY_SCHEMA)
            writer.write_table(table)
            
        writer.close()

    # ==========================================
    # 4. KÖZPONTI VEZÉRLÉS ÉS VALIDÁCIÓ
    # ==========================================
    def run_test(self):
        print(f"\n🚀 [1/3] Rendszer szimuláció indítása: {self.target_hz} Hz ({self.duration_sec} másodperc)...")
        
        if os.path.exists(self.output_file):
            os.remove(self.output_file)
            
        self.is_running = True
        
        producer = threading.Thread(target=self._mock_openxr_producer, daemon=True)
        consumer = threading.Thread(target=self._parquet_consumer, daemon=True)
        
        producer.start()
        consumer.start()
        
        time.sleep(self.duration_sec)
        
        print(f"🛑 [2/3] Mérés leállítása. Adatok szinkronizálása a lemezre...")
        self.is_running = False
        producer.join()
        consumer.join()
        
        self.verify_data_loss()

    def verify_data_loss(self):
        print(f"\n🔬 [3/3] Tudományos Validáció: Adatvesztés Ellenőrzése...")
        
        # Parquet gyors betöltése
        df = pd.read_parquet(self.output_file)
        
        # Nanoszekundumból másodperc (1e9)
        df['time_sec'] = df['timestamp_ns'] / 1e9
        
        # Két sor közötti időkülönbség
        df['delta_time'] = df['time_sec'].diff().fillna(1.0 / self.target_hz)
        
        ideal_dt = 1.0 / self.target_hz
        tolerance = ideal_dt * 1.5 # 1.5x késés már frame drop-nak számít
        
        dropped_frames = df[df['delta_time'] > tolerance]
        loss_pct = (len(dropped_frames) / len(df)) * 100
        avg_dt = df['delta_time'].mean()
        max_dt = df['delta_time'].max()
        
        print("\n" + "="*50)
        print("📊 TUDOMÁNYOS ADATVESZTÉS JELENTÉS (PARQUET)")
        print("="*50)
        print(f"Generált Frame-ek:      {self.frames_generated}")
        print(f"Mentett Frame-ek:       {len(df)}")
        print(f"Célzott Frissítés:      {self.target_hz} Hz")
        print(f"Átlagos Ciklusidő:      {avg_dt:.6f} mp (Ideális: {ideal_dt:.6f})")
        print(f"Max Ciklus Késés:       {max_dt:.6f} mp")
        print("-" * 50)
        print(f"Kimaradt (Drop) Minta:  {len(dropped_frames)} db")
        
        if loss_pct < 0.1:
            print(f"✅ ADATVESZTÉS:          {loss_pct:.4f}% (Sikeres Validáció)")
        else:
            print(f"⚠️ ADATVESZTÉS:          {loss_pct:.4f}% (Kritikus)")
        print("="*50 + "\n")

if __name__ == "__main__":
    test = VRLossAnalyzerTest(target_hz=90, duration_sec=10)
    test.run_test()