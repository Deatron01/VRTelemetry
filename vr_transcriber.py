import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import tkinter as tk
from tkinter import filedialog
import warnings

# Figyelmeztetések elrejtése (a Whisper néha sokat panaszkodik a konzolban a formátumok miatt)
warnings.filterwarnings("ignore")
current_dir = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] += os.pathsep + current_dir
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

AUDIO_FILE = os.path.join(session_dir, "audio_microphone.wav")
OUTPUT_TXT = os.path.join(session_dir, "transcript.txt")

if not os.path.exists(AUDIO_FILE):
    print(f"[UGRÁS] Nem található mikrofon felvétel ({AUDIO_FILE}). Nincs mit átírni.")
    sys.exit(0)

print(f"\n---> Hanganyag betöltése innen: {session_dir}")

try:
    import whisper
    
    print("Whisper AI (Turbo modell) betöltése... (Első alkalommal le is tölti a modellt!)")
    # A 'turbo' modell már kiválóan ért magyarul, de nem eszi meg az összes RAM-ot.
    # model = whisper.load_model("turbo") 
    model = whisper.load_model("small")
    
    print("Hanganyag mesterséges intelligencia alapú elemzése folyamatban...")
    # A transcribe funkció magától felismeri a nyelvet (pl. magyart)
    result = model.transcribe(AUDIO_FILE, language="en", condition_on_previous_text=True)
    
    print(f"Átírás kész! Mentés ide: {OUTPUT_TXT}")
    
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write("Automatikus Audio Leirat (Whisper AI)\n")
        f.write("="*50 + "\n\n")
        
        # Végigmegyünk a mondatokon, és időbélyeggel (másodperc) mentjük őket
        for segment in result["segments"]:
            start = round(segment["start"], 1)
            end = round(segment["end"], 1)
            text = segment["text"].strip()
            f.write(f"[{start}s - {end}s]: {text}\n")
            
except Exception as e:
    print(f"Hiba a Whisper AI futtatásakor: {e}")
    sys.exit(1)