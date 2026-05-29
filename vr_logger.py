import tkinter as tk
from tkinter import ttk, messagebox
import openvr
import threading
import time
import csv
import math
from datetime import datetime
from PIL import ImageGrab
import os
import pygetwindow as gw
import sys
import subprocess

# Új importok a hangrögzítéshez
import soundcard as sc
import soundfile as sf
import numpy as np

# Terminál kódolásának javítása (ékezetes betűk miatt)
sys.stdout.reconfigure(encoding='utf-8')

class VRTelemetryLogger:
    def __init__(self, root):
        self.root = root
        self.root.title("Project Mimir - VR QA Logger")
        self.root.geometry("450x250")
        self.root.resizable(False, False)

        self.is_recording = False
        self.audio_threads_running = False
        self.record_thread = None
        self.vr_system = None

        self.setup_gui()

    def setup_gui(self):
        style = ttk.Style()
        style.configure("TButton", font=("Helvetica", 12))
        
        self.status_var = tk.StringVar(value="Státusz: Készenlét (Várakozás a SteamVR-ra)")
        
        ttk.Label(self.root, text="Minden Adat Rögzítése (6DoF + Audio)", font=("Helvetica", 14, "bold")).pack(pady=15)
        self.status_label = ttk.Label(self.root, textvariable=self.status_var, font=("Helvetica", 10))
        self.status_label.pack(pady=10)

        self.btn_start = ttk.Button(self.root, text="▶ Felvétel Indítása", command=self.start_recording)
        self.btn_start.pack(pady=10, fill=tk.X, padx=50)

        self.btn_stop = ttk.Button(self.root, text="⏹ Felvétel Leállítása", command=self.stop_recording, state=tk.DISABLED)
        self.btn_stop.pack(pady=5, fill=tk.X, padx=50)

    def init_vr(self):
        try:
            self.vr_system = openvr.init(openvr.VRApplication_Overlay)
            return True
        except openvr.OpenVRError as e:
            messagebox.showerror("VR Hiba", f"Nem sikerült csatlakozni a SteamVR-hoz.\n{e}")
            return False

    def start_recording(self):
        if not self.init_vr():
            return
        
        self.is_recording = True
        self.audio_threads_running = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        
        # --- MUNKAMENET (SESSION) MAPPA LÉTREHOZÁSA ---
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join("Sessions", f"Session_{timestamp}")
        self.screenshot_dir = os.path.join(self.session_dir, "screenshots")
        
        os.makedirs(self.screenshot_dir, exist_ok=True) 
        
        # Fájlok elérési útjai
        self.filename = os.path.join(self.session_dir, "telemetry.csv")
        self.mic_file = os.path.join(self.session_dir, "audio_microphone.wav")
        self.game_audio_file = os.path.join(self.session_dir, "audio_stereo_game.wav")

        self.status_var.set(f"Státusz: Rögzítés a '{self.session_dir}' mappába...")

        # Adatgyűjtő és hangrögzítő szálak indítása
        self.record_thread = threading.Thread(target=self.recording_loop, daemon=True)
        self.mic_thread = threading.Thread(target=self.record_microphone, daemon=True)
        self.game_audio_thread = threading.Thread(target=self.record_game_audio, daemon=True)
        
        self.record_thread.start()
        self.mic_thread.start()
        self.game_audio_thread.start()

    # ==========================================
    # HANG RÖGZÍTŐ FÜGGVÉNYEK
    # ==========================================
    def record_microphone(self):
        try:
            mic = sc.default_microphone()
            with mic.recorder(samplerate=48000) as recorder, \
                 sf.SoundFile(self.mic_file, mode='w', samplerate=48000, channels=1) as file:
                while self.audio_threads_running:
                    data = recorder.record(numframes=24000)
                    file.write(data[:, 0]) # Mono mentés
        except Exception as e:
            print(f"Hiba a mikrofon rögzítésekor: {e}")

    def record_game_audio(self):
        try:
            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(id=speaker.id, include_loopback=True)
            with loopback_mic.recorder(samplerate=48000) as recorder, \
                 sf.SoundFile(self.game_audio_file, mode='w', samplerate=48000, channels=2) as file:
                while self.audio_threads_running:
                    data = recorder.record(numframes=24000)
                    file.write(data) # Sztereó mentés
        except Exception as e:
            print(f"Hiba a játékhang rögzítésekor: {e}")

    # ==========================================
    # VEZÉRLÉS ÉS PIPELINE TRIGGER
    # ==========================================
    def stop_recording(self):
        self.is_recording = False
        self.audio_threads_running = False # Hangrögzítés leállítása
        
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        
        if self.vr_system:
            openvr.shutdown()
            self.vr_system = None

        self.status_var.set(f"Státusz: Rögzítés leállítva. Adatfeldolgozás indítása...")
        threading.Thread(target=self.trigger_pipeline, daemon=True).start()

    def trigger_pipeline(self):
        try:
            subprocess.run([sys.executable, "run_pipeline.py", self.session_dir], check=True)
            self.status_var.set(f"Státusz: KÉSZ! Az eredmények a '{os.path.basename(self.session_dir)}' mappában.")
        except Exception as e:
            self.status_var.set("Státusz: Hiba történt az automatikus feldolgozás során.")
            print(f"Hiba a pipeline hívásakor: {e}")

    def matrix_to_euler(self, m):
        sy = math.sqrt(m[0][0] * m[0][0] + m[1][0] * m[1][0])
        if sy > 1e-6:
            x = math.atan2(m[2][1], m[2][2])
            y = math.atan2(-m[2][0], sy)
            z = math.atan2(m[1][0], m[0][0])
        else:
            x = math.atan2(-m[1][2], m[1][1])
            y = math.atan2(-m[2][0], sy)
            z = 0
        return [math.degrees(x), math.degrees(y), math.degrees(z)]

    # ==========================================
    # FŐ ADATGYŰJTŐ CIKLUS
    # ==========================================
    def recording_loop(self):
        # 1. FEJLÉC ÖSSZEÁLLÍTÁSA
        headers = ["Timestamp"]
        devices = ["HMD", "LeftCtrl", "RightCtrl"]
        
        last_screenshot_time = 0 
        for dev in devices:
            headers.extend([
                f"{dev}_PosX", f"{dev}_PosY", f"{dev}_PosZ",
                f"{dev}_RotX", f"{dev}_RotY", f"{dev}_RotZ",
                f"{dev}_LinVelX", f"{dev}_LinVelY", f"{dev}_LinVelZ",
                f"{dev}_AngVelX", f"{dev}_AngVelY", f"{dev}_AngVelZ"
            ])
            if dev in ["LeftCtrl", "RightCtrl"]:
                headers.extend([f"{dev}_Trigger", f"{dev}_Grip", f"{dev}_JoyX", f"{dev}_JoyY"])
                
        # --- ÚJ: Bővített szemkövetési oszlopok a kutatáshoz ---
        headers.extend(["Eye_Gaze_X", "Eye_Gaze_Y", "Eye_Gaze_Z", "Pupil_Size_L", "Pupil_Size_R"]) 

        # 2. ADATGYŰJTÉS
        with open(self.filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(headers)

            while self.is_recording:
                current_time_obj = datetime.now()
                timestamp_str = current_time_obj.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                # KÉPERNYŐKÉP MENTÉSE (Másodpercenként 1x)
                current_time_sec = time.time()
                if current_time_sec - last_screenshot_time >= 1.0:
                    try:
                        vr_windows = gw.getWindowsWithTitle('VR View')
                        if vr_windows:
                            win = vr_windows[0]
                            img = ImageGrab.grab(bbox=(win.left, win.top, win.right, win.bottom))
                        else:
                            img = ImageGrab.grab()
                            
                        img_name = os.path.join(self.screenshot_dir, f"frame_{current_time_obj.strftime('%H%M%S')}.jpg")
                        threading.Thread(target=img.save, args=(img_name, "JPEG")).start()
                    except Exception as e:
                        print(f"Képlopási hiba: {e}")
                        
                    last_screenshot_time = current_time_sec
                
                # ADATOK LEKÉRÉSE A STEAMVR-BÓL
                poses = self.vr_system.getDeviceToAbsoluteTrackingPose(
                    openvr.TrackingUniverseStanding, 0, openvr.k_unMaxTrackedDeviceCount)
                
                # Alapértelmezetten mindent 0.0-ra állítunk (így a szemadatok is 0-k maradnak, amíg nincs megfelelő hardver)
                data_row = {col: 0.0 for col in headers}
                data_row["Timestamp"] = timestamp_str

                for i in range(openvr.k_unMaxTrackedDeviceCount):
                    if poses[i].bPoseIsValid:
                        device_class = self.vr_system.getTrackedDeviceClass(i)
                        
                        prefix = None
                        if device_class == openvr.TrackedDeviceClass_HMD:
                            prefix = "HMD"
                        elif device_class == openvr.TrackedDeviceClass_Controller:
                            role = self.vr_system.getControllerRoleForTrackedDeviceIndex(i)
                            if role == openvr.TrackedControllerRole_LeftHand:
                                prefix = "LeftCtrl"
                            elif role == openvr.TrackedControllerRole_RightHand:
                                prefix = "RightCtrl"

                        if prefix:
                            matrix = poses[i].mDeviceToAbsoluteTracking
                            data_row[f"{prefix}_PosX"] = matrix[0][3]
                            data_row[f"{prefix}_PosY"] = matrix[1][3]
                            data_row[f"{prefix}_PosZ"] = matrix[2][3]
                            
                            rot = self.matrix_to_euler(matrix)
                            data_row[f"{prefix}_RotX"] = rot[0]
                            data_row[f"{prefix}_RotY"] = rot[1]
                            data_row[f"{prefix}_RotZ"] = rot[2]

                            data_row[f"{prefix}_LinVelX"] = poses[i].vVelocity[0]
                            data_row[f"{prefix}_LinVelY"] = poses[i].vVelocity[1]
                            data_row[f"{prefix}_LinVelZ"] = poses[i].vVelocity[2]

                            data_row[f"{prefix}_AngVelX"] = math.degrees(poses[i].vAngularVelocity[0])
                            data_row[f"{prefix}_AngVelY"] = math.degrees(poses[i].vAngularVelocity[1])
                            data_row[f"{prefix}_AngVelZ"] = math.degrees(poses[i].vAngularVelocity[2])

                            if "Ctrl" in prefix:
                                result, pState = self.vr_system.getControllerState(i)
                                if result:
                                    data_row[f"{prefix}_JoyX"] = pState.rAxis[0].x
                                    data_row[f"{prefix}_JoyY"] = pState.rAxis[0].y
                                    data_row[f"{prefix}_Trigger"] = pState.rAxis[1].x
                                    data_row[f"{prefix}_Grip"] = pState.rAxis[2].x

                # Adatok sorba rendezése a fejléc alapján és mentés
                row = [data_row[col] for col in headers]
                writer.writerow(row)
                file.flush()

                time.sleep(0.02) # ~50Hz

if __name__ == "__main__":
    root = tk.Tk()
    app = VRTelemetryLogger(root)
    def on_closing():
        if app.is_recording:
            app.stop_recording()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()