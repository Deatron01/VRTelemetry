import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import tkinter as tk
from tkinter import filedialog

class VRAIPreprocessor:
    def __init__(self, session_dir):
        self.session_dir = session_dir
        self.raw_file = os.path.join(session_dir, "telemetry_raw.parquet")
        self.ai_file = os.path.join(session_dir, "ai_ready_telemetry.parquet")
        self.etl_meta_file = os.path.join(session_dir, "etl_metadata.json")
        self.version = "v1.1.0" # Verzió frissítve a kinematikai bővítés miatt

    def process(self):
        print("="*50)
        print(f"🧠 VR AI TENZOR GENERÁLÓ (ETL PIPELINE) - {self.version}")
        print("="*50)
        print(f"[*] Célmappa: {os.path.basename(self.session_dir)}")
        
        # 1. KIVONÁS (EXTRACT)
        if not os.path.exists(self.raw_file):
            print(f"[HIBA] Nem található nyers Parquet fájl: {self.raw_file}")
            print("Győződj meg róla, hogy a mérés lezárult!")
            return
        
        df = pd.read_parquet(self.raw_file)
        original_len = len(df)
        print(f"[+] Nyers adat betöltve: {original_len} képkocka (frame).")

        # 2. TISZTÍTÁS ÉS INTERPOLÁCIÓ (TRANSFORM - Step 1)
        # Ha a sisak egy pillanatra elvesztette a követést, a Pandas lineárisan 
        # kitölti az űrt, hogy a neurális háló ne kapjon NaN (üres) hibát.
        missing_values_before = df.isna().sum().sum()
        df = df.interpolate(method='linear').bfill().ffill()
        
        # 3. ZAJCSÖKKENTÉS / SIMÍTÁS (TRANSFORM - Step 2)
        # Exponenciális mozgóátlagot (EMA) használunk a kéz- és fejremegés (jitter) 
        # kisimítására, így az AI csak a valódi szándékos mozgást tanulja meg.
        smooth_cols = [c for c in df.columns if 'pos_' in c or 'rot_' in c]
        df[smooth_cols] = df[smooth_cols].ewm(span=5, adjust=False).mean()
        print("[+] Tracker zajszűrés (EMA) alkalmazva.")

        # --- KINEMATIKAI FEATURE ENGINEERING (REQ-02) ---
        print("[+] Kinematikai deriváltak (Sebesség) számítása...")
        
        # Mivel a mérési ablak fix (REQ-02), a dt konstans.
        dt = 1.0 / 90.0  # 90Hz feltételezése alapján
        
        pos_columns = [c for c in df.columns if 'pos_' in c]
        for col in pos_columns:
            vel_col = col.replace('pos_', 'vel_')
            # Egyszerű deriválás a simított adaton (sebesség = út / idő)
            df[vel_col] = df[col].diff() / dt
            df[vel_col] = df[vel_col].fillna(0.0) # A legelső frame-nél nincs sebesség
            
        # VII. Táblázat Származtatott Feature: Kéztávolság (V-05, V-06)
        if 'target_obj_pos_x' in df.columns:
            df['dist_to_target_left'] = np.sqrt(
                (df['left_pos_x'] - df['target_obj_pos_x'])**2 +
                (df['left_pos_y'] - df['target_obj_pos_y'])**2 +
                (df['left_pos_z'] - df['target_obj_pos_z'])**2
            )
            df['dist_to_target_right'] = np.sqrt(
                (df['right_pos_x'] - df['target_obj_pos_x'])**2 +
                (df['right_pos_y'] - df['target_obj_pos_y'])**2 +
                (df['right_pos_z'] - df['target_obj_pos_z'])**2
            )
        # ------------------------------------------------

        # 4. NORMALIZÁLÁS (TRANSFORM - Step 3)
        # A Neurális hálók (LSTM, Transformer) akkor tanulnak a leggyorsabban, 
        # ha minden bemenet nagyjából -1 és 1, vagy 0 és 1 között van.
        
        # A) Z-Score Standardizálás a pozíciókra ÉS az új sebességekre
        norm_cols = [c for c in df.columns if 'pos_' in c or 'vel_' in c or 'distance' in c or 'pupil' in c or 'amplitude' in c or 'dist_to_' in c]
        for col in norm_cols:
            std_val = df[col].std()
            if std_val > 0.0001:  # Nullával osztás elkerülése
                df[col] = (df[col] - df[col].mean()) / std_val
            else:
                df[col] = 0.0 
                
        # B) Százalékos értékek 0-1 közé skálázása (Min-Max)
        percentage_cols = ['cpu_utilization', 'gpu_utilization', 'battery_hmd', 'battery_left', 'battery_right']
        for col in percentage_cols:
            if col in df.columns:
                # Biztosítjuk, hogy 100-nál ne legyen nagyobb, majd elosztjuk
                df[col] = df[col].clip(0, 100) / 100.0

        if 'app_fps' in df.columns:
            df['app_fps'] = (df['app_fps'] / 120.0).clip(0, 1) # Max 120Hz referenciához
            
        print("[+] Bemeneti tenzorok normalizálása (Z-Score & MinMax) befejezve.")

        # 5. BETÖLTÉS (LOAD)
        df.to_parquet(self.ai_file, compression='snappy')
        print(f"[+] AI-Kész Tenzor kimentve: {self.ai_file}")

        # 6. ADAT-EREDET (PROVENANCE) METAADATOK MENTÉSE (VIII. Táblázat)
        etl_meta = {
            "data_provenance": {
                "preprocessor_version": self.version,
                "smoothing_algorithm": "Exponential Moving Average (span=5)",
                "scaling_method": "Z-Score Standardization (Pos & Vel) & MinMax (Sys)",
                "velocity_deriv_method": "First-order Difference (dt=1/90)", # Frissítve a kódnak megfelelően
                "outlier_removal": "Linear Interpolation & Forward/Backward Fill",
                "total_dropped_frames": int(missing_values_before), 
                "processed_at": datetime.now(timezone.utc).isoformat()
            }
        }
        
        with open(self.etl_meta_file, "w", encoding="utf-8") as f:
            json.dump(etl_meta, f, indent=4)
            
        print(f"[+] ETL Dokumentáció kimentve: {self.etl_meta_file}")
        print("="*50)
        print("✅ A FÁJL KÉSZEN ÁLL A GÉPI TANÍTÁSRA (PyTorch / TensorFlow)!")
        print("="*50)

if __name__ == "__main__":
    # Ha a fő pipeline hívja meg (run_pipeline.py), akkor megkapja argumentumként:
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        # Külön futtatva feldob egy ablakot
        root = tk.Tk()
        root.withdraw()
        target_dir = filedialog.askdirectory(title="Válaszd ki a Session mappát az AI feldolgozáshoz", initialdir="Sessions")
        
    if target_dir:
        processor = VRAIPreprocessor(target_dir)
        processor.process()