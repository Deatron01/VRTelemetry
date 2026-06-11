import sys
import os
import uvicorn
import webbrowser
import threading
import time
import multiprocessing
import runpy

# --- KIKÉNYSZERÍTETT IMPORTOK (AI / Hangátírás NÉLKÜL) ---
import server 
import tkinter
import tkinter.filedialog
import tkinter.messagebox
import pandas
import turtle
import numpy
import matplotlib
import matplotlib.pyplot
import seaborn
import cv2
import plotly
import scipy

# --- 1. MUNKAKÖNYVTÁR ZÁROLÁSA MINDEN FOLYAMATNAK ---
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- 2. A "TRÜKK" ---
if len(sys.argv) > 1 and sys.argv[1].endswith(".py"):
    script_to_run = sys.argv[1]
    sys.argv = sys.argv[1:] 
    runpy.run_path(script_to_run, run_name="__main__")
    sys.exit(0) 

def open_browser():
    time.sleep(2)
    print("\n---> Böngésző megnyitása... <---")
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    os.makedirs("Sessions", exist_ok=True)
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("VR Telemetry Rendszer indítása...")
    uvicorn.run(server.app, host="127.0.0.1", port=8000, log_level="info")