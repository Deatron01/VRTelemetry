import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import tkinter as tk
from tkinter import filedialog
import pandas as pd
import numpy as np
import glob
import cv2
import matplotlib.pyplot as plt
# ==========================================
# AUTOMATIKUS MAPPAVÁLASZTÓ LOGIKA
# ==========================================
# Ha a Mester Script indítja, megkapja a mappát argumentumként
if len(sys.argv) > 1:
    session_dir = sys.argv[1]
else:
    # Ha kézzel indítod, felugrik a választó ablak
    root = tk.Tk()
    root.withdraw()
    session_dir = filedialog.askdirectory(title="Válaszd ki a Session mappát", initialdir="Sessions")
    if not session_dir:
        sys.exit("Nem választottál mappát. Kilépés.")

CSV_FILE = os.path.join(session_dir, "telemetry.csv")

if not os.path.exists(CSV_FILE):
    sys.exit(f"Hiba: Nem találtam 'telemetry.csv' fájlt itt: {session_dir}")
BLUR_SIZE = 151       # A Gauss-elmosás mértéke (Páratlan számnak kell lennie!)
DOT_SIZE = 40         # A nyers fókuszpont mérete pixelben
INTENSITY = 0.6
HEATMAP_RADIUS = 150
# Eredmények mentési helyei az aktuális mappán belül:
OUTPUT_HTML = os.path.join(session_dir, "vr_3d_heatmap.html")          # A 3D hőtérképhez
SCREENSHOT_DIR = os.path.join(session_dir, "screenshots")              # A 2D hőtérképhez
OUTPUT_HEATMAP_DIR = os.path.join(session_dir, "heatmaps_2d")          # A 2D hőtérképhez
DASHBOARD_IMG = os.path.join(session_dir, "qa_dashboard_results.png")  # Az Analyzerhez

print(f"\n---> Adatok betöltése innen: {session_dir}")
df = pd.read_csv(CSV_FILE)
df['Timestamp'] = pd.to_datetime(df['Timestamp'])

# Képek megkeresése a mappában
image_files = sorted(glob.glob(os.path.join(SCREENSHOT_DIR, "*.jpg")))
if not image_files:
    print(f"Hiba: Nem találtam képeket a {SCREENSHOT_DIR} mappában!")
    exit()

print(f"{len(image_files)} kép feldolgozása indul...")

# ==========================================
# HŐTÉRKÉP GENERÁLÁSA
# ==========================================
for img_path in image_files:
    # 1. Képfájl beolvasása és méreteinek kinyerése
    frame = cv2.imread(img_path)
    if frame is None:
        continue
    height, width, _ = frame.shape
    
    # Kép időbélyegének kinyerése a fájlnévből (pl: frame_142530.jpg -> 14:25:30)
    filename = os.path.basename(img_path)
    time_str = filename.split('_')[1].split('.')[0] # '142530'
    
    # 2. Megkeressük a CSV-ben az ehhez az időponthoz tartozó legközelebbi adatsort
    # Mivel csak a HHMMSS van a fájlnévben, csinálunk egy közelítő keresést
    df['TimeStr'] = df['Timestamp'].dt.strftime('%H%M%S')
    matching_rows = df[df['TimeStr'] == time_str]
    
    # Létrehozunk egy üres, fekete "vászont", amire a hőtérképet fogjuk rajzolni
    heatmap_layer = np.zeros((height, width), dtype=np.float32)
    
    if not matching_rows.empty:
        # 3. TEKINTET (GAZE) POZÍCIÓJÁNAK MEGHATÁROZÁSA
        # Mivel egy másodperc alatt a logger 50 adatot mentett (50Hz), mind az 50 pontot rárajzoljuk,
        # így kialakul a "hő", ha sokat nézett egy helyre.
        
        for index, row in matching_rows.iterrows():
            # QUEST 2 SZIMULÁCIÓ: A képernyő közepe, amit a fej forgási sebessége picit eltol
            # (Ha lenne igazi Eye_Gaze oszlopunk Quest Pro-ból, itt azt használnánk!)
            
            # Alapértelmezett tekintet a képernyő közepe
            gaze_x = width // 2
            gaze_y = height // 2
            
            # Szimulált szemmozgás: Ha a fej hirtelen fordul (AngVel), a szem a mozgás irányába "siet"
            # Skálázzuk a szögsebességet, hogy pixelben kifejezhető eltolódást adjon
            yaw_speed = row['HMD_AngVelY'] # Vízszintes fejmozgás
            pitch_speed = row['HMD_AngVelX'] # Függőleges fejmozgás
            
            gaze_x += int(yaw_speed * 1.5) 
            gaze_y -= int(pitch_speed * 1.5) # Y tengely lefelé nő a képeken
            
            # Határokon belül tartjuk a pontot
            gaze_x = max(0, min(width - 1, gaze_x))
            gaze_y = max(0, min(height - 1, gaze_y))
            
            # Egy "hőfolt" hozzáadása a vászonhoz
            left_eye_center_x = int(width * 0.25)  # A bal térfél közepe (Bal szem)
            right_eye_center_x = int(width * 0.75) # A jobb térfél közepe (Jobb szem)
            center_y = int(height * 0.5)           # Függőlegesen középen marad (Szemmagasság)

            # Később, ha a szemkövetős sisak adatai (Eye_Gaze_X, Y) megérkeznek,
            # itt tudod majd eltolni a left_eye és right_eye központokat!
            
            # Két külön "hőgömböt" rajzolunk a heatmap_layer-re a két szemnek megfelelően
            cv2.circle(heatmap_layer, (left_eye_center_x, center_y), int(HEATMAP_RADIUS * 0.5), 1.0, -1)
            cv2.circle(heatmap_layer, (right_eye_center_x, center_y), int(HEATMAP_RADIUS * 0.5), 1.0, -1)
            # ---------------------------------------------------

    # 4. HŐTÉRKÉP KISZÍNEZÉSE ÉS ELMOSÁSA
    # Erős elmosás, hogy ne éles körök, hanem "felhők" legyenek
    heatmap_layer = cv2.GaussianBlur(heatmap_layer, (BLUR_SIZE | 1, BLUR_SIZE | 1), 0)
    
    # Normalizálás 0-255 közé
    heatmap_layer = np.clip(heatmap_layer * 255 * 5, 0, 255).astype(np.uint8)
    
    # A szürkeárnyalatos hőfelhő átszínezése klasszikus hőtérkép (Jet/Inferno) színekre
    color_heatmap = cv2.applyColorMap(heatmap_layer, cv2.COLORMAP_JET)
    
    # Csak ott színezzük át a képet, ahol valóban van "hő" (maszkolás)
    mask = heatmap_layer > 10
    
    # Az eredeti kép és a hőtérkép összeolvasztása
    result_img = frame.copy()
    blended = cv2.addWeighted(frame, 1 - INTENSITY, color_heatmap, INTENSITY, 0)
    result_img[mask] = blended[mask]
    
    # 5. EREDMÉNY MENTÉSE
    # Létrehozzuk az almappát a Session-ön belül, ha még nem létezne
    os.makedirs(OUTPUT_HEATMAP_DIR, exist_ok=True)
        
    # Elmentjük a képet az új változónevet használva
    output_path = os.path.join(OUTPUT_HEATMAP_DIR, f"heatmap_{filename}")
    cv2.imwrite(output_path, result_img)

print(f"Kész! A hőtérképes képeket megtalálod a '{OUTPUT_HEATMAP_DIR}' mappában.")