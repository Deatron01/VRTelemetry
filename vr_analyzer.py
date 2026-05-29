import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import tkinter as tk
from tkinter import filedialog
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
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

# Eredmények mentési helyei az aktuális mappán belül:
OUTPUT_HTML = os.path.join(session_dir, "vr_3d_heatmap.html")          # A 3D hőtérképhez
SCREENSHOT_DIR = os.path.join(session_dir, "screenshots")              # A 2D hőtérképhez
OUTPUT_HEATMAP_DIR = os.path.join(session_dir, "heatmaps_2d")          # A 2D hőtérképhez
DASHBOARD_IMG = os.path.join(session_dir, "qa_dashboard_results.png")  # Az Analyzerhez

print(f"\n---> Adatok betöltése innen: {session_dir}")
df = pd.read_csv(CSV_FILE)
df['Timestamp'] = pd.to_datetime(df['Timestamp'])
df['Time_Sec'] = (df['Timestamp'] - df['Timestamp'].iloc[0]).dt.total_seconds()

# ==========================================
# 2. ADATOK ELŐKÉSZÍTÉSE ÉS METRIKÁK SZÁMÍTÁSA
# ==========================================
metrics = {}

for prefix in ['HMD', 'LeftCtrl', 'RightCtrl']:
    # Fizikai távolság (Pithagorasz-tétel: Vektor hossza a pozícióváltozásokból)
    dist = np.sqrt(
        df[f'{prefix}_PosX'].diff()**2 + 
        df[f'{prefix}_PosY'].diff()**2 + 
        df[f'{prefix}_PosZ'].diff()**2
    ).fillna(0)
    metrics[f'{prefix}_TotalDist'] = dist.sum()
    
    # Lineáris sebesség magnitúdója (eredő sebességvektor)
    # Képlet: $\sqrt{v_x^2 + v_y^2 + v_z^2}$
    df[f'{prefix}_Velocity_Mag'] = np.sqrt(
        df[f'{prefix}_LinVelX']**2 + 
        df[f'{prefix}_LinVelY']**2 + 
        df[f'{prefix}_LinVelZ']**2
    )
    
    # Szögsebesség magnitúdója (eredő forgási sebesség)
    df[f'{prefix}_AngVel_Mag'] = np.sqrt(
        df[f'{prefix}_AngVelX']**2 + 
        df[f'{prefix}_AngVelY']**2 + 
        df[f'{prefix}_AngVelZ']**2
    )
    
    # Tremor Index: A szögsebesség szórása (jitter) egy rövid időablakban.
    # Kiválóan mutatja a kéz remegését vagy a fej bizonytalan mozgását.
    df[f'{prefix}_Tremor'] = df[f'{prefix}_AngVel_Mag'].rolling(window=25).std().fillna(0)

# ==========================================
# 3. VIZUALIZÁCIÓ (6-PANELES DASHBOARD)
# ==========================================
fig = plt.figure(figsize=(20, 12))
fig.suptitle("Teljes Körű VR QA Telemetria", fontsize=22, fontweight='bold', color='white')

# --- 1. Térbeli Útvonal (3D) ---
ax1 = fig.add_subplot(3, 2, 1, projection='3d')
ax1.plot(df['HMD_PosX'], df['HMD_PosZ'], df['HMD_PosY'], label='Fej', color='cyan', alpha=0.8)
ax1.plot(df['LeftCtrl_PosX'], df['LeftCtrl_PosZ'], df['LeftCtrl_PosY'], label='Bal Kéz', color='red', alpha=0.6)
ax1.plot(df['RightCtrl_PosX'], df['RightCtrl_PosZ'], df['RightCtrl_PosY'], label='Jobb Kéz', color='lime', alpha=0.6)
ax1.set_title('Térbeli Mozgás (3D Path)')
ax1.set_xlabel('X (m)')
ax1.set_ylabel('Z (m)')
ax1.set_zlabel('Y (m)')
ax1.legend()

# --- 2. Fej Rotáció (Pitch, Yaw, Roll) - Kiberbetegség indikátor ---
ax2 = fig.add_subplot(3, 2, 2)
ax2.plot(df['Time_Sec'], df['HMD_RotX'], label='Pitch (Bólintás)', color='magenta')
ax2.plot(df['Time_Sec'], df['HMD_RotY'], label='Yaw (Forgatás)', color='yellow')
ax2.plot(df['Time_Sec'], df['HMD_RotZ'], label='Roll (Döntés)', color='cyan')
ax2.set_title('Fej Forgása (Euler-szögek)')
ax2.set_ylabel('Fok (°)')
ax2.grid(True, alpha=0.2)
ax2.legend()

# --- 3. Sebesség Profil (Hardveres adatok alapján) ---
ax3 = fig.add_subplot(3, 2, 3)
ax3.plot(df['Time_Sec'], df['HMD_Velocity_Mag'], label='Fej Sebesség', color='cyan')
ax3.plot(df['Time_Sec'], df['LeftCtrl_Velocity_Mag'], label='Bal Kéz', color='red', alpha=0.6)
ax3.plot(df['Time_Sec'], df['RightCtrl_Velocity_Mag'], label='Jobb Kéz', color='lime', alpha=0.6)
ax3.set_title('Fizikai Sebesség (m/s)')
ax3.set_ylabel('Sebesség')
ax3.grid(True, alpha=0.2)
ax3.legend()

# --- 4. Kontroller Inputok (Gombnyomások / Ergonómia) ---
ax4 = fig.add_subplot(3, 2, 4)
ax4.fill_between(df['Time_Sec'], df['RightCtrl_Trigger'], alpha=0.5, color='lime', label='Jobb Ravasz (Trigger)')
ax4.fill_between(df['Time_Sec'], df['RightCtrl_Grip'], alpha=0.3, color='green', label='Jobb Markolat (Grip)')
ax4.fill_between(df['Time_Sec'], df['LeftCtrl_Trigger'] * -1, alpha=0.5, color='red', label='Bal Ravasz (Tükrözve)')
ax4.fill_between(df['Time_Sec'], df['LeftCtrl_Grip'] * -1, alpha=0.3, color='darkred', label='Bal Markolat (Tükrözve)')
ax4.set_title('Felhasználói Interakciók (Inputok)')
ax4.set_ylabel('Lenyomás mértéke (0.0 - 1.0)')
ax4.grid(True, alpha=0.2)
ax4.legend(loc='upper right')

# --- 5. Tremor / Stabilitás Index (Szögsebességből számítva) ---
ax5 = fig.add_subplot(3, 2, 5)
ax5.plot(df['Time_Sec'], df['LeftCtrl_Tremor'], label='Bal Kéz Remegés', color='red')
ax5.plot(df['Time_Sec'], df['RightCtrl_Tremor'], label='Jobb Kéz Remegés', color='lime')
ax5.set_title('Finommotoros Tremor Index')
ax5.set_xlabel('Idő (s)')
ax5.set_ylabel('Szögsebesség Szórása')
ax5.grid(True, alpha=0.2)
ax5.legend()

# --- 6. Összesített Fizikai Terhelés (Távolságok) ---
ax6 = fig.add_subplot(3, 2, 6)
bars = ax6.bar(['Fej (HMD)', 'Bal Kéz', 'Jobb Kéz'], 
               [metrics['HMD_TotalDist'], metrics['LeftCtrl_TotalDist'], metrics['RightCtrl_TotalDist']],
               color=['cyan', 'red', 'lime'], alpha=0.8)
ax6.set_title('Fizikai Terhelés (Összes Megtett Távolság)')
ax6.set_ylabel('Távolság (Méter)')

for bar in bars:
    yval = bar.get_height()
    ax6.text(bar.get_x() + bar.get_width()/2, yval + 0.1, f'{yval:.2f} m', ha='center', va='bottom', color='white', fontweight='bold')

plt.tight_layout(rect=[0, 0.03, 1, 0.95])

# --- ÚJ: MENTÉS MEGJELENÍTÉS HELYETT ---
# Elmentjük a képet a korábban definiált DASHBOARD_IMG útvonalra.
# A facecolor biztosítja, hogy a sötét háttér is belekerüljön a képbe (ne legyen átlátszó/fehér).
plt.savefig(DASHBOARD_IMG, dpi=300, facecolor=fig.get_facecolor(), edgecolor='none')
print(f"Műszerfal kimentve: {DASHBOARD_IMG}")

# Bezárjuk a memóriában lévő ábrát, hogy ne egye meg a RAM-ot a háttérben
plt.close(fig)
# ---------------------------------------