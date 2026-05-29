import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import tkinter as tk
from tkinter import filedialog
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.stats import gaussian_kde
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

# ==========================================
# 3D LÁTÓTÉR BEÁLLÍTÁSOK (Ide kerültek vissza!)
# ==========================================
OPTIMAL_DIST = 1.5       # A fókuszpont távolsága (méter)
DIST_SPREAD = 1.0        # Fókusz elmosódása
FOV_DEGREES = 25.0       # Látószög (kúp szélessége)
# ==========================================

# Hogy minden adat (gyors mozgások is) látszódjon, felemeljük a limitet
# Így a kúpok sűrűn követik egymást, és egybefüggő felhőt alkotnak.
MAX_POINTS = 12000
if len(df) > MAX_POINTS:
    step = len(df) // MAX_POINTS
    df = df.iloc[::step].copy()
    print(f"Adatmennyiség optimalizálva {len(df)} keretre a folytonosság megtartásával.")
else:
    print(f"Minden adat feldolgozása ({len(df)} keret)...")

x = df['HMD_PosX'].values
y = df['HMD_PosY'].values 
z = df['HMD_PosZ'].values 
rot_x = df['HMD_RotX'].values 
rot_y = df['HMD_RotY'].values 

eye_x = df['Eye_Gaze_X'].values
eye_y = df['Eye_Gaze_Y'].values
eye_z = df['Eye_Gaze_Z'].values

# ==========================================
# 3D RÁCS ELŐKÉSZÍTÉSE
# ==========================================
PADDING = 3.0 
grid_size = 40 # Finomabb rács a szebb, folytonos ködért

xi = np.linspace(x.min() - PADDING, x.max() + PADDING, grid_size)
yi = np.linspace(y.min() - PADDING, y.max() + PADDING, grid_size)
zi = np.linspace(z.min() - PADDING, z.max() + PADDING, grid_size)

X, Y, Z = np.meshgrid(xi, yi, zi, indexing='ij')
grid_coords = np.vstack([X.ravel(), Y.ravel(), Z.ravel()]).T 
density_volume = np.zeros(len(grid_coords))

min_dot = np.cos(np.radians(FOV_DEGREES))

gaze_points_x = []
gaze_points_y = []
gaze_points_z = []

print("Látótér folyamatos kiszámítása (Ez eltarthat pár másodpercig!)...")

# ==========================================
# FŐ CIKLUS: MINDEN ADATPONT RÖGZÍTÉSE
# ==========================================
for i in range(len(df)):
    pos = np.array([x[i], y[i], z[i]])
    
    yaw = np.radians(rot_y[i])
    pitch = np.radians(rot_x[i])
    
    forward = np.array([
        np.sin(yaw) * np.cos(pitch),
        -np.sin(pitch), 
        -np.cos(yaw) * np.cos(pitch)
    ])
    
    eye_vec = np.array([eye_x[i], eye_y[i], eye_z[i]])
    if np.linalg.norm(eye_vec) > 0.01:
        forward = forward + (eye_vec * 0.5) 
        
    forward = forward / np.linalg.norm(forward) 
    
    focus_point = pos + (forward * OPTIMAL_DIST)
    gaze_points_x.append(focus_point[0])
    gaze_points_y.append(focus_point[1])
    gaze_points_z.append(focus_point[2])
    
    diff = grid_coords - pos
    dist = np.linalg.norm(diff, axis=1)
    dist[dist < 0.01] = 0.01 
    
    dirs = diff / dist[:, np.newaxis] 
    dots = np.dot(dirs, forward)
    
    angular_weight = np.maximum(0, (dots - min_dot) / (1 - min_dot))
    dist_weight = np.exp(-0.5 * ((dist - OPTIMAL_DIST) / DIST_SPREAD)**2)
    
    density_volume += angular_weight * dist_weight

# ==========================================
# INTERAKTÍV 3D PLOT FELÉPÍTÉSE
# ==========================================
print("3D modell renderelése...")
density_volume = density_volume.reshape(X.shape)
fig = go.Figure()

# 1. Réteg: Teljes, folytonos Volumetrikus hőtérkép
fig.add_trace(go.Volume(
    x=X.ravel(),
    y=Z.ravel(), 
    z=Y.ravel(), 
    value=density_volume.ravel(),
    # NAGYON ALACSONY KÜSZÖB: Így a leggyorsabb mozgás (halvány hő) is látszódni fog!
    isomin=density_volume.max() * 0.02, 
    isomax=density_volume.max(),
    opacity=0.25,
    surface_count=20, # Sűrűbb, "füstösebb" megjelenés
    colorscale='Plasma', 
    colorbar=dict(title="Összesített<br>Figyelem")
))

# 2. Réteg: A folyamatos tekintet-vonal (Ciánkék)
fig.add_trace(go.Scatter3d(
    x=gaze_points_x, 
    y=gaze_points_z, 
    z=gaze_points_y, 
    mode='lines', # Itt kivettem a "markers"-t (pöttyöket), hogy egy sima vonal legyen
    line=dict(color='cyan', width=2),
    opacity=0.7,
    name='Fókuszpont Útvonala'
))

# 3. Réteg: Fizikai HMD útvonal
fig.add_trace(go.Scatter3d(
    x=x, y=z, z=y,
    mode='lines',
    line=dict(color='white', width=1.5, dash='dot'),
    opacity=0.3,
    name='Fizikai Fej Útvonal'
))

fig.update_layout(
    title="Teljes, Folytonos Látótér Hőtérkép",
    template="plotly_dark",
    scene=dict(
        xaxis_title='X - Oldalirány (m)',
        yaxis_title='Z - Mélység (m)',
        zaxis_title='Y - Magasság (m)',
        aspectmode='data'
    ),
    margin=dict(l=0, r=0, b=0, t=50),
    legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
)

fig.write_html(OUTPUT_HTML)
print(f"Kész! Nyisd meg a böngésződben a '{OUTPUT_HTML}' fájlt!")