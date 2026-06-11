import sys
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json

# A fej nélküli logger importálása
from vr_logger import vr_logger_instance

app = FastAPI(title="VR Telemetry API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. KÖNYVTÁRAK DINAMIKUS MEGHATÁROZÁSA ---
# Ez garantálja, hogy az exe és a sima python script is megtalálja a mappákat!
if getattr(sys, 'frozen', False):
    # Ha becsomagolt exe-ből fut, az exe mappáját vesszük gyökérnek
    ROOT_DIR = os.path.dirname(sys.executable)
else:
    # Ha sima fejlesztői python scriptként fut, akkor a script mappáját
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 2. ELÉRÉSI ÚTVONALAK ÖSSZEÁLLÍTÁSA ---
SESSIONS_DIR = os.path.join(ROOT_DIR, "Sessions")
FRONTEND_DIR = os.path.join(ROOT_DIR, "vr-telemetry-ui", "dist")

if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

app.mount("/Sessions", StaticFiles(directory=SESSIONS_DIR), name="sessions")

# Frontend (React) statikus fájlok (JS, CSS) csatolása
if os.path.exists(FRONTEND_DIR):
    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# --- 3. FŐOLDAL KISZOLGÁLÁSA ---
@app.get("/")
async def serve_frontend():
    # A főoldalon magát az index.html-t adjuk vissza
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    # Ha hiba van, pontosan megmondja, hol hiányzik a fájl!
    return {"message": f"CRITICAL: A frontend (index.html) nem talalhato ezen az utvonalon: {index_path}"}

# --- 4. FELVÉTEL VEZÉRLÉS ---
@app.get("/api/record/max-fps")
async def get_max_fps():
    # Visszaadja a csatlakoztatott VR sisak max frissítési rátáját
    return {"max_fps": vr_logger_instance.get_max_refresh_rate()}

@app.post("/api/record/start")
async def start_record(sampling_rate: int = 90):
    # A React-ből kapott sebességgel indítja a loggert
    return vr_logger_instance.start_recording(sampling_rate)

@app.post("/api/record/pause")
async def pause_record():
    return vr_logger_instance.pause_recording()

@app.post("/api/record/stop")
async def stop_record():
    return vr_logger_instance.stop_recording()

@app.get("/api/record/status")
async def get_record_status():
    return {
        "is_recording": vr_logger_instance.is_recording,
        "is_paused": vr_logger_instance.is_paused
    }

# --- 5. ADATOK LEKÉRDEZÉSE ---
@app.get("/api/sessions")
async def get_sessions():
    try:
        sessions = [d for d in os.listdir(SESSIONS_DIR) if os.path.isdir(os.path.join(SESSIONS_DIR, d))]
        sessions.sort(reverse=True)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/{session_id}")
async def get_session_details(session_id: str):
    session_path = os.path.join(SESSIONS_DIR, session_id)
    if not os.path.exists(session_path):
        raise HTTPException(status_code=404, detail="Session nem található")
    
    # --- METAADATOK BEOLVASÁSA ---
    metadata = {}
    meta_path = os.path.join(session_path, "metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
    images = []
    graphs_dir = os.path.join(session_path, "graphs")
    if os.path.exists(graphs_dir):
        for img in sorted(os.listdir(graphs_dir)):
            if img.endswith(".png"):
                title = img.replace(".png", "").replace("_", " ")
                if title[0:2].isdigit(): title = title[3:]
                images.append({"title": title, "url": f"http://127.0.0.1:8000/Sessions/{session_id}/graphs/{img}"})
                
    heatmaps_2d = []
    heatmaps_dir = os.path.join(session_path, "heatmaps_2d")
    if os.path.exists(heatmaps_dir):
        for img in sorted(os.listdir(heatmaps_dir)):
            if img.endswith(".jpg") or img.endswith(".png"):
                heatmaps_2d.append(f"http://127.0.0.1:8000/Sessions/{session_id}/heatmaps_2d/{img}")
    
    transcript = "Nem készült hang leirat."
    transcript_path = os.path.join(session_path, "transcript.txt")
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = f.read()

    return {
        "metadata": metadata,  # <--- EZ A KULCS! Ezt adja át a React-nek!
        "images": images,
        "heatmaps_2d": heatmaps_2d,
        "transcript": transcript,
        "heatmap_url": f"http://127.0.0.1:8000/Sessions/{session_id}/vr_3d_heatmap.html" if os.path.exists(os.path.join(session_path, "vr_3d_heatmap.html")) else None,
        "mic_url": f"http://127.0.0.1:8000/Sessions/{session_id}/audio_microphone.wav" if os.path.exists(os.path.join(session_path, "audio_microphone.wav")) else None,
        "game_url": f"http://127.0.0.1:8000/Sessions/{session_id}/audio_stereo_game.wav" if os.path.exists(os.path.join(session_path, "audio_stereo_game.wav")) else None,
        "playback_url": f"http://127.0.0.1:8000/Sessions/{session_id}/vr_playback.html" if os.path.exists(os.path.join(session_path, "vr_playback.html")) else None
    }