# server.py (A Python főkönyvtárba)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import subprocess

app = FastAPI(title="VR Telemetry API")

# CORS beállítása: Ez engedi meg, hogy a React frontend (ami máshonnan fut) lekérje az adatokat
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS_DIR = "Sessions"
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

# 1. Statikus fájlok kiszolgálása (Ezzel látja a React a képeket, zenéket, HTML-t)
app.mount("/Sessions", StaticFiles(directory=SESSIONS_DIR), name="sessions")

# 2. Mérések listázása
@app.get("/api/sessions")
def get_sessions():
    try:
        sessions = [d for d in os.listdir(SESSIONS_DIR) if os.path.isdir(os.path.join(SESSIONS_DIR, d))]
        sessions.sort(reverse=True)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. Konkrét mérés adatainak lekérése
@app.get("/api/sessions/{session_id}")
def get_session_details(session_id: str):
    session_path = os.path.join(SESSIONS_DIR, session_id)
    if not os.path.exists(session_path):
        raise HTTPException(status_code=404, detail="Session nem található")
    
    # Generált grafikonok kigyűjtése
    graphs_dir = os.path.join(session_path, "graphs")
    images = []
    if os.path.exists(graphs_dir):
        # A fájlnevekből szép címeket generálunk és URL-t csatolunk hozzá
        for img in sorted(os.listdir(graphs_dir)):
            if img.endswith(".png"):
                title = img.replace(".png", "").replace("_", " ")
                if title[0:2].isdigit(): title = title[3:]
                images.append({"title": title, "url": f"http://localhost:8000/Sessions/{session_id}/graphs/{img}"})
    
    # Szöveges leirat (Transcript) beolvasása
    transcript = "Nem készült hang leirat."
    transcript_path = os.path.join(session_path, "transcript.txt")
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = f.read()

    # Visszaadjuk az összes elérési utat JSON formátumban
    return {
        "images": images,
        "transcript": transcript,
        "heatmap_url": f"http://localhost:8000/Sessions/{session_id}/vr_3d_heatmap.html" if os.path.exists(os.path.join(session_path, "vr_3d_heatmap.html")) else None,
        "mic_url": f"http://localhost:8000/Sessions/{session_id}/audio_microphone.wav" if os.path.exists(os.path.join(session_path, "audio_microphone.wav")) else None,
        "game_url": f"http://localhost:8000/Sessions/{session_id}/audio_stereo_game.wav" if os.path.exists(os.path.join(session_path, "audio_stereo_game.wav")) else None,
    }

# 4. Új Mérés / Elemzés indítása a pipeline-al
@app.post("/api/run-pipeline")
def run_pipeline():
    try:
        subprocess.run(["python", "run_pipeline.py"], check=True)
        return {"status": "success"}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail="Hiba a feldolgozás során.")