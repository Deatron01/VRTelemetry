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
# BEÁLLÍTÁSOK ÉS BIOMECHANIKAI PARAMÉTEREK
# ==========================================
WEIGHT_KG = 115  # Kalóriaégetés (MET) számításához
HEIGHT_CM = 184  # Magasság profilhoz
# A headset (HMD) szemmagassága álló helyzetben (kb. 15 cm-rel a testmagasság alatt)
STANDING_HMD_HEIGHT = (HEIGHT_CM - 15) / 100.0  

# ==========================================
# AUTOMATIKUS MAPPAVÁLASZTÓ LOGIKA
# ==========================================
if len(sys.argv) > 1:
    session_dir = sys.argv[1]
else:
    root = tk.Tk()
    root.withdraw()
    session_dir = filedialog.askdirectory(title="Válaszd ki a Session mappát", initialdir="Sessions")
    if not session_dir:
        sys.exit("Nem választottál mappát. Kilépés.")

CSV_FILE = os.path.join(session_dir, "telemetry.csv")

if not os.path.exists(CSV_FILE):
    sys.exit(f"Hiba: Nem találtam 'telemetry.csv' fájlt itt: {session_dir}")

# Külön mappa a grafikonoknak, hogy ne legyen káosz
GRAPHS_DIR = os.path.join(session_dir, "graphs")
os.makedirs(GRAPHS_DIR, exist_ok=True)

print(f"\n---> Adatok betöltése innen: {session_dir}")
df = pd.read_csv(CSV_FILE)
df['Timestamp'] = pd.to_datetime(df['Timestamp'])
df['Time_Sec'] = (df['Timestamp'] - df['Timestamp'].iloc[0]).dt.total_seconds()

# ==========================================
# 2. ADATOK ELŐKÉSZÍTÉSE ÉS ÚJ METRIKÁK
# ==========================================
metrics = {}
dt = df['Time_Sec'].diff().fillna(0.011) # Idő delta a gyorsuláshoz

for prefix in ['HMD', 'LeftCtrl', 'RightCtrl']:
    # Fizikai távolság
    dist = np.sqrt(
        df[f'{prefix}_PosX'].diff()**2 + 
        df[f'{prefix}_PosY'].diff()**2 + 
        df[f'{prefix}_PosZ'].diff()**2
    ).fillna(0)
    metrics[f'{prefix}_TotalDist'] = dist.sum()
    
    # Sebesség magnitúdója
    df[f'{prefix}_Velocity_Mag'] = np.sqrt(
        df[f'{prefix}_LinVelX']**2 + 
        df[f'{prefix}_LinVelY']**2 + 
        df[f'{prefix}_LinVelZ']**2
    )
    
    # Gyorsulás (sebesség deriváltja)
    df[f'{prefix}_Accel_Mag'] = (df[f'{prefix}_Velocity_Mag'].diff() / dt).fillna(0)
    
    # Szögsebesség magnitúdója
    df[f'{prefix}_AngVel_Mag'] = np.sqrt(
        df[f'{prefix}_AngVelX']**2 + 
        df[f'{prefix}_AngVelY']**2 + 
        df[f'{prefix}_AngVelZ']**2
    )
    
    # Tremor Index
    df[f'{prefix}_Tremor'] = df[f'{prefix}_AngVel_Mag'].rolling(window=25).std().fillna(0)

# --- KAROK KINYÚJTÁSA (Arm Extension - Push/Pull metrika) ---
df['LeftArm_Ext'] = np.sqrt((df['HMD_PosX'] - df['LeftCtrl_PosX'])**2 +
                            (df['HMD_PosY'] - df['LeftCtrl_PosY'])**2 +
                            (df['HMD_PosZ'] - df['LeftCtrl_PosZ'])**2)

df['RightArm_Ext'] = np.sqrt((df['HMD_PosX'] - df['RightCtrl_PosX'])**2 +
                             (df['HMD_PosY'] - df['RightCtrl_PosY'])**2 +
                             (df['HMD_PosZ'] - df['RightCtrl_PosZ'])**2)

# --- ENERGIAFELHASZNÁLÁS BECSLÉSE (Kcal) ---
# MET érték becslése a sebességből (1.5 = állás/pihenés, 8.0 = intenzív mozgás)
df['Estimated_MET'] = 1.5 + (df['HMD_Velocity_Mag'] * 3.0).clip(upper=10.0)
cumulative_time_hours = df['Time_Sec'].iloc[-1] / 3600.0
total_kcal = df['Estimated_MET'].mean() * WEIGHT_KG * cumulative_time_hours

# ==========================================
# 3. ÁBRÁK GENERÁLÁSA ÉS MENTÉSE EGYENKÉNT
# ==========================================
plt.style.use('dark_background')
BG_COLOR = '#0E1117' # Streamlit sötét téma háttere

def save_plot(fig, filename):
    out_path = os.path.join(GRAPHS_DIR, filename)
    fig.tight_layout()
    fig.savefig(out_path, dpi=300, facecolor=BG_COLOR, edgecolor='none')
    plt.close(fig)
    print(f"Mentve: {filename}")
    
# --- ÚJ BIOMECHANIKAI ÉS ORVOSI SZÁMÍTÁSOK ---

# 1. Ízületi terhelés (Jerk) - Gyorsulás deriváltja
for prefix in ['LeftCtrl', 'RightCtrl']:
    df[f'{prefix}_Jerk'] = (df[f'{prefix}_Accel_Mag'].diff() / dt).fillna(0).abs()

# 2. Kiberbetegség (Cybersickness) Index
# A Roll (Z) és Pitch (X) forgás okozza a legnagyobb vesztibuláris zavart
df['Cybersickness_Index'] = (df['HMD_AngVelZ'].abs() * 2.0) + (df['HMD_AngVelX'].abs() * 1.5) + (df['HMD_AngVelY'].abs() * 0.5)
df['Cybersickness_Rolling'] = df['Cybersickness_Index'].rolling(window=50).mean().fillna(0)

# 3. Kifáradási görbe (Sebesség mozgóátlaga hosszú ablakon)
# A fillna(method='bfill') helyett közvetlenül a bfill()-t használjuk:
df['Left_Fatigue'] = df['LeftCtrl_Velocity_Mag'].rolling(window=300).mean().bfill()
df['Right_Fatigue'] = df['RightCtrl_Velocity_Mag'].rolling(window=300).mean().bfill()

# 4. Intenzitási zónák kiszámítása a MET alapján
# Zónák: Pihenő (<3), Mérsékelt (3-6), Intenzív (>6)
conditions = [
    (df['Estimated_MET'] < 3.0),
    (df['Estimated_MET'] >= 3.0) & (df['Estimated_MET'] < 6.0),
    (df['Estimated_MET'] >= 6.0)
]
choices = ['Pihenő / Könnyű', 'Mérsékelt (Zsírégető)', 'Intenzív (Kardió)']
df['Intensity_Zone'] = np.select(conditions, choices, default='Pihenő / Könnyű')
zone_counts = df['Intensity_Zone'].value_counts()

# --- 1. Térbeli Útvonal (3D) ---
fig1 = plt.figure(figsize=(10, 8), facecolor=BG_COLOR)
ax1 = fig1.add_subplot(111, projection='3d')
ax1.set_facecolor(BG_COLOR)
ax1.plot(df['HMD_PosX'], df['HMD_PosZ'], df['HMD_PosY'], label='Fej', color='cyan', alpha=0.8)
ax1.plot(df['LeftCtrl_PosX'], df['LeftCtrl_PosZ'], df['LeftCtrl_PosY'], label='Bal Kéz', color='red', alpha=0.6)
ax1.plot(df['RightCtrl_PosX'], df['RightCtrl_PosZ'], df['RightCtrl_PosY'], label='Jobb Kéz', color='lime', alpha=0.6)
ax1.set_title('Térbeli Mozgás (3D Path)')
ax1.legend()
save_plot(fig1, "01_3D_Path.png")

# --- 2. Fej Rotáció ---
fig2, ax2 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax2.plot(df['Time_Sec'], df['HMD_RotX'], label='Pitch (Bólintás)', color='magenta')
ax2.plot(df['Time_Sec'], df['HMD_RotY'], label='Yaw (Forgatás)', color='yellow')
ax2.plot(df['Time_Sec'], df['HMD_RotZ'], label='Roll (Döntés)', color='cyan')
ax2.set_title('Fej Forgása (Kiberbetegség indikátor)')
ax2.set_ylabel('Fok (°)')
ax2.grid(True, alpha=0.2)
ax2.legend()
save_plot(fig2, "02_Head_Rotation.png")

# --- 3. Sebesség Profil ---
fig3, ax3 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax3.plot(df['Time_Sec'], df['HMD_Velocity_Mag'], label='Fej Sebesség', color='cyan')
ax3.plot(df['Time_Sec'], df['LeftCtrl_Velocity_Mag'], label='Bal Kéz', color='red', alpha=0.6)
ax3.plot(df['Time_Sec'], df['RightCtrl_Velocity_Mag'], label='Jobb Kéz', color='lime', alpha=0.6)
ax3.set_title('Fizikai Sebesség (m/s)')
ax3.grid(True, alpha=0.2)
ax3.legend()
save_plot(fig3, "03_Velocity_Profile.png")

# --- 4. Gyorsulás Profil (Robbanékonyság) ---
fig4, ax4 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax4.plot(df['Time_Sec'], df['LeftCtrl_Accel_Mag'], label='Bal Kéz Gyorsulás', color='red', alpha=0.7)
ax4.plot(df['Time_Sec'], df['RightCtrl_Accel_Mag'], label='Jobb Kéz Gyorsulás', color='lime', alpha=0.7)
ax4.set_title('Kézmozdulatok Gyorsulása (Robbanékonyság)')
ax4.set_ylabel('m/s^2')
ax4.grid(True, alpha=0.2)
ax4.legend()
save_plot(fig4, "04_Acceleration_Profile.png")

# --- 5. Kontroller Inputok ---
fig5, ax5 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax5.fill_between(df['Time_Sec'], df['RightCtrl_Trigger'], alpha=0.5, color='lime', label='Jobb Ravasz')
ax5.fill_between(df['Time_Sec'], df['RightCtrl_Grip'], alpha=0.3, color='green', label='Jobb Markolat')
ax5.fill_between(df['Time_Sec'], df['LeftCtrl_Trigger'] * -1, alpha=0.5, color='red', label='Bal Ravasz (Tükrözve)')
ax5.fill_between(df['Time_Sec'], df['LeftCtrl_Grip'] * -1, alpha=0.3, color='darkred', label='Bal Markolat')
ax5.set_title('Felhasználói Interakciók (Inputok)')
ax5.grid(True, alpha=0.2)
ax5.legend(loc='upper right')
save_plot(fig5, "05_Controller_Inputs.png")

# --- 6. Tremor / Stabilitás ---
fig6, ax6 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax6.plot(df['Time_Sec'], df['LeftCtrl_Tremor'], label='Bal Kéz Remegés', color='red')
ax6.plot(df['Time_Sec'], df['RightCtrl_Tremor'], label='Jobb Kéz Remegés', color='lime')
ax6.set_title('Finommotoros Tremor Index (Stabilitás)')
ax6.grid(True, alpha=0.2)
ax6.legend()
save_plot(fig6, "06_Tremor_Index.png")

# --- 7. Távolság Összesítő ---
fig7, ax7 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
bars = ax7.bar(['Fej (HMD)', 'Bal Kéz', 'Jobb Kéz'], 
               [metrics['HMD_TotalDist'], metrics['LeftCtrl_TotalDist'], metrics['RightCtrl_TotalDist']],
               color=['cyan', 'red', 'lime'], alpha=0.8)
ax7.set_title('Fizikai Terhelés (Összes Megtett Távolság)')
for bar in bars:
    yval = bar.get_height()
    ax7.text(bar.get_x() + bar.get_width()/2, yval + 0.1, f'{yval:.2f} m', ha='center', va='bottom', color='white', fontweight='bold')
save_plot(fig7, "07_Total_Distance.png")

# --- 8. Magasság és Guggolás Profil ---
fig8, ax8 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax8.axhline(y=STANDING_HMD_HEIGHT, color='white', linestyle='--', alpha=0.5, label=f'Álló magasság ({HEIGHT_CM} cm)')
ax8.plot(df['Time_Sec'], df['HMD_PosY'], color='cyan', label='Aktuális fejmagasság (Y)')
ax8.set_title('Magasság Profil és Guggolás Analízis')
ax8.set_ylabel('Magasság (m)')
ax8.grid(True, alpha=0.2)
ax8.legend()
save_plot(fig8, "08_Squat_Posture_Profile.png")

# --- 9. Karok Kinyújtása (Arm Extension) ---
fig9, ax9 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax9.plot(df['Time_Sec'], df['LeftArm_Ext'], color='red', alpha=0.7, label='Bal Kar')
ax9.plot(df['Time_Sec'], df['RightArm_Ext'], color='lime', alpha=0.7, label='Jobb Kar')
ax9.set_title('Karok Kinyújtása (Távolság a fejtől)')
ax9.set_ylabel('Méter')
ax9.grid(True, alpha=0.2)
ax9.legend()
save_plot(fig9, "09_Arm_Extension.png")

# --- 10. Felülnézeti (2D) Tevékenység Heatmap ---
fig10, ax10 = plt.subplots(figsize=(8, 8), facecolor=BG_COLOR)
sns.kdeplot(x=df['HMD_PosX'], y=df['HMD_PosZ'], cmap="mako", fill=True, bw_adjust=0.5, ax=ax10)
ax10.set_title('Felülnézeti Tevékenység (HMD X-Z Sík)')
ax10.set_xlabel('X Pozíció')
ax10.set_ylabel('Z Pozíció')
save_plot(fig10, "10_TopDown_Heatmap.png")

# --- 11. Fejforgatás Eloszlása (Nézési irány) ---
fig11, ax11 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
sns.histplot(df['HMD_RotY'], bins=50, color='yellow', kde=True, ax=ax11)
ax11.set_title('Fókuszpont eloszlása (Yaw)')
ax11.set_xlabel('Szög (°)')
ax11.set_ylabel('Gyakoriság')
save_plot(fig11, "11_Yaw_Distribution.png")

# --- 12. Energiafelhasználás és Intenzitás ---
fig12, ax12 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax12.plot(df['Time_Sec'], df['Estimated_MET'], color='orange', label='Aktuális Intenzitás (MET)')
ax12.fill_between(df['Time_Sec'], df['Estimated_MET'], color='orange', alpha=0.2)
ax12.set_title(f'Energiafelhasználás (Becsült Elégetett Kalória: {total_kcal:.1f} kcal)')
ax12.set_ylabel('MET (Metabolic Equivalent)')
ax12.set_xlabel('Idő (s)')
ax12.grid(True, alpha=0.2)
ax12.legend()
save_plot(fig12, "12_Energy_Expenditure.png")

# --- 13. Kiberbetegség Kockázat (Cybersickness Susceptibility) ---
fig13, ax13 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax13.plot(df['Time_Sec'], df['Cybersickness_Rolling'], color='red', label='Rosszullét Kockázati Index')
ax13.axhline(y=df['Cybersickness_Rolling'].mean() + df['Cybersickness_Rolling'].std()*2, color='orange', linestyle='--', label='Kritikus Küszöb')
ax13.set_title('Kiberbetegség Kockázati Index (VIMS)')
ax13.set_ylabel('Vesztibuláris Terhelés')
ax13.set_xlabel('Idő (s)')
ax13.grid(True, alpha=0.2)
ax13.legend()
save_plot(fig13, "13_Cybersickness_Risk.png")

# --- 14. Mozgási Aszimmetria (Bal vs. Jobb Izomegyensúly) ---
fig14, ax14 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
asym_labels = ['Megtett Út (m)', 'Átlagos Sebesség (m/s)', 'Átlagos Kinyújtás (m)']
left_vals = [metrics['LeftCtrl_TotalDist'], df['LeftCtrl_Velocity_Mag'].mean(), df['LeftArm_Ext'].mean()]
right_vals = [metrics['RightCtrl_TotalDist'], df['RightCtrl_Velocity_Mag'].mean(), df['RightArm_Ext'].mean()]

x = np.arange(len(asym_labels))
width = 0.35
ax14.bar(x - width/2, left_vals, width, label='Bal Kar', color='red', alpha=0.8)
ax14.bar(x + width/2, right_vals, width, label='Jobb Kar', color='lime', alpha=0.8)
ax14.set_title('Mozgási Aszimmetria (Bal vs. Jobb Dominancia)')
ax14.set_xticks(x)
ax14.set_xticklabels(asym_labels)
ax14.legend()
save_plot(fig14, "14_Movement_Asymmetry.png")

# --- 15. "VR Nyak" - Nyakcsigolya Terhelés (Fej Pitch) ---
fig15, ax15 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
# Feltételezve, hogy a HMD_RotX negatív, ha lefelé néz (SteamVR specifikus lehet, szükség esetén -1-gyel szorozható)
sns.kdeplot(df['HMD_RotX'], fill=True, color='purple', ax=ax15)
ax15.axvline(x=0, color='white', linestyle='--', label='Egyenes fejtartás (0°)')
ax15.axvline(x=-20, color='red', linestyle='--', label='Kritikus lefelé dőlés (-20°)')
ax15.axvline(x=20, color='red', linestyle='--')
ax15.set_title('Testtartás Analízis (Nyakcsigolya Terhelés)')
ax15.set_xlabel('Bólintás Szöge (Pitch °)')
ax15.legend()
save_plot(fig15, "15_Cervical_Strain_Posture.png")

# --- 16. Ízületi Terhelés (Jerk / Rántás) ---
fig16, ax16 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax16.plot(df['Time_Sec'], df['LeftCtrl_Jerk'], color='red', alpha=0.6, label='Bal Kar Rántás')
ax16.plot(df['Time_Sec'], df['RightCtrl_Jerk'], color='lime', alpha=0.6, label='Jobb Kar Rántás')
ax16.set_title('Ízületi Terhelés (Jerk - Hirtelen mozdulatok)')
ax16.set_ylabel('Rántás (m/s³)')
ax16.set_xlabel('Idő (s)')
ax16.grid(True, alpha=0.2)
ax16.legend()
save_plot(fig16, "16_Joint_Stress_Jerk.png")

# --- 17. Kifáradási Profil (Teljesítmény esés) ---
fig17, ax17 = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
ax17.plot(df['Time_Sec'], df['Left_Fatigue'], color='red', label='Bal Kar (Mozgóátlag)')
ax17.plot(df['Time_Sec'], df['Right_Fatigue'], color='lime', label='Jobb Kar (Mozgóátlag)')
ax17.set_title('Kifáradási Görbe (Dinamika csökkenése)')
ax17.set_ylabel('Átlagos Sebesség (m/s)')
ax17.set_xlabel('Idő (s)')
ax17.grid(True, alpha=0.2)
ax17.legend()
save_plot(fig17, "17_Fatigue_Profile.png")

# --- 18. Intenzitási Zónák Eloszlása (Modernizált Fánk Diagram) ---
fig18, ax18 = plt.subplots(figsize=(8, 8), facecolor=BG_COLOR)

# Fix szín-hozzárendelés a zónákhoz, hogy a sorrend ne rontsa el a vizualizációt
zone_color_map = {
    'Pihenő / Könnyű': '#3b82f6',    # Kék
    'Mérsékelt (Zsírégető)': '#10b981', # Zöld
    'Intenzív (Kardió)': '#ef4444'      # Piros
}

# Kinyerjük a pontos színeket a zone_counts aktuális sorrendje alapján
mapped_colors = [zone_color_map.get(zone, '#888888') for zone in zone_counts.index]

# Diagram megrajzolása
wedges, texts, autotexts = ax18.pie(
    zone_counts.values, 
    labels=zone_counts.index, 
    autopct='%1.1f%%', 
    startangle=140, 
    colors=mapped_colors, 
    textprops={'color': "white", 'fontsize': 12, 'fontweight': 'bold'},
    wedgeprops={'linewidth': 3, 'edgecolor': BG_COLOR} # Vastagabb elválasztó vonalak a sötét háttér színével
)

# Belső "lyuk" létrehozása a fánk (Donut) stílushoz
centre_circle = plt.Circle((0, 0), 0.65, fc=BG_COLOR)
fig18.gca().add_artist(centre_circle)

# Középső felirat hozzáadása
ax18.text(0, 0, 'Intenzitás\nZónák', ha='center', va='center', fontsize=18, fontweight='bold', color='white', alpha=0.8)

ax18.set_title('Edzés Intenzitási Zónák Eloszlása', color='white', fontsize=16, pad=20)
save_plot(fig18, "18_Intensity_Zones.png")

print(f"\n✅ Összesen 12 analitikai ábra sikeresen elmentve a {GRAPHS_DIR} mappába!")