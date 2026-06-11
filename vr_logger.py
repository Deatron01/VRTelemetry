import openvr
import threading
import time
import csv
import math
from datetime import datetime
from PIL import ImageGrab
import os
import pygetwindow as gw
import soundcard as sc
import soundfile as sf
import subprocess
import sys

# ÚJ IMPORTOK A METAADATOKHOZ (Ezek beépített Python modulok, nem kell pip install!)
import platform
import socket
import json

sys.stdout.reconfigure(encoding='utf-8')

class HeadlessVRLogger:
    def __init__(self):
        self.is_recording = False
        self.is_paused = False
        self.audio_threads_running = False
        self.vr_system = None
        self.session_dir = None
        self.sampling_rate = 90

    def init_vr(self):
        if self.vr_system is not None:
            return True
        try:
            self.vr_system = openvr.init(openvr.VRApplication_Overlay)
            return True
        except openvr.OpenVRError as e:
            print(f"VR Hiba: {e}")
            return False

    def get_max_refresh_rate(self):
        if not self.init_vr():
            return 90
        try:
            freq = self.vr_system.getFloatTrackedDeviceProperty(
                openvr.k_unTrackedDeviceIndex_Hmd, 
                openvr.Prop_DisplayFrequency_Float
            )
            return int(freq) if freq > 0 else 90
        except:
            return 90

    # --- ÚJ FUNKCIÓ: METAADATOK GYŰJTÉSE ---
    def save_metadata(self):
        # GPU adatok lekérése (ez a könyvtár már használatban van a rendszerben)
        gpu_info = {}
        try:
            import GPUtil
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu_info = {
                    "Nev": gpus[0].name,
                    "VRAM_Total": f"{gpus[0].memoryTotal} MB",
                    "Homerseklet": f"{gpus[0].temperature} C",
                    "Terheltseg": f"{gpus[0].load * 100:.1f} %"
                }
        except:
            gpu_info = {"Hiba": "GPUtil nem elérhető"}

        meta = {
            "Rendszer": {
                "OS_Rendszer": platform.system(),
                "OS_Verzio": platform.version(),
                "OS_Kiadas": platform.release(),
                "Architektura": platform.machine(),
                "Processzor": platform.processor(),
                "CPU_Magok": os.cpu_count(),
            },
            "Felhasznalo_es_Halozat": {
                "Gepnev": socket.gethostname(),
                "Felhasznalo": os.getlogin() if hasattr(os, 'getlogin') else 'Ismeretlen',
                "Python_Verzio": platform.python_version()
            },
            "Hardver_Extra": {
                "GPU": gpu_info,
                "RAM_Total": f"{round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / (1024.**3), 2)} GB" if hasattr(os, 'sysconf') else "Ismeretlen"
            },
            "VR_Hardver": {},
            "Meres_Adatai": {
                "Mintavetelezes": f"{self.sampling_rate} Hz",
                "Inditas_Ideje": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Munkakonyvtar": os.getcwd()
            }
        }
        
        # VR Hardver információk
        if self.vr_system:
            try:
                meta["VR_Hardver"] = {
                    "Gyarto": self.vr_system.getStringTrackedDeviceProperty(openvr.k_unTrackedDeviceIndex_Hmd, openvr.Prop_ManufacturerName_String),
                    "Modell": self.vr_system.getStringTrackedDeviceProperty(openvr.k_unTrackedDeviceIndex_Hmd, openvr.Prop_ModelNumber_String),
                    "Szeriaszam": self.vr_system.getStringTrackedDeviceProperty(openvr.k_unTrackedDeviceIndex_Hmd, openvr.Prop_SerialNumber_String),
                    "Koveto_Rendszer": self.vr_system.getStringTrackedDeviceProperty(openvr.k_unTrackedDeviceIndex_Hmd, openvr.Prop_TrackingSystemName_String),
                    "Display_Freq": self.get_max_refresh_rate()
                }
            except:
                meta["VR_Hardver"]["Hiba"] = "Adatok olvasása sikertelen."
        else:
            meta["VR_Hardver"]["Statusz"] = "Nincs VR sisak csatlakoztatva."

        # Mentes
        meta_file = os.path.join(self.session_dir, "metadata.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4, ensure_ascii=False)

    def start_recording(self, sampling_rate=90):
        if self.is_recording:
            return {"status": "error", "message": "A felvétel már fut!"}
        if not self.init_vr():
            return {"status": "error", "message": "Nem sikerült csatlakozni a SteamVR-hoz."}
        
        self.sampling_rate = sampling_rate
        self.is_recording = True
        self.is_paused = False
        self.audio_threads_running = True
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join("Sessions", f"Session_{timestamp}")
        self.screenshot_dir = os.path.join(self.session_dir, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True) 
        
        # --- ITT HÍVJUK MEG A METAADAT MENTŐT A MAPPA LÉTREHOZÁSA UTÁN ---
        self.save_metadata()
        
        self.filename = os.path.join(self.session_dir, "telemetry.csv")
        self.mic_file = os.path.join(self.session_dir, "audio_microphone.wav")
        self.game_audio_file = os.path.join(self.session_dir, "audio_stereo_game.wav")

        threading.Thread(target=self.recording_loop, daemon=True).start()
        threading.Thread(target=self.record_microphone, daemon=True).start()
        threading.Thread(target=self.record_game_audio, daemon=True).start()

        return {"status": "success", "message": f"Felvétel elindítva ({self.sampling_rate} Hz).", "session": self.session_dir}

    def pause_recording(self):
        if not self.is_recording:
            return {"status": "error", "message": "Nincs futó felvétel."}
        self.is_paused = not self.is_paused
        állapot = "Szüneteltetve" if self.is_paused else "Folytatva"
        return {"status": "success", "message": f"Felvétel {állapot}."}

    def stop_recording(self):
        if not self.is_recording:
            return {"status": "error", "message": "Nincs futó felvétel."}
        
        self.is_recording = False
        self.is_paused = False
        self.audio_threads_running = False
        
        if self.vr_system:
            openvr.shutdown()
            self.vr_system = None

        threading.Thread(target=self.trigger_pipeline, daemon=True).start()
        return {"status": "success", "message": "Felvétel leállítva, feldolgozás indítva."}

    def trigger_pipeline(self):
        try:
            print("Pipeline automatikus indítása...")
            subprocess.run([sys.executable, "run_pipeline.py", self.session_dir], check=True)
            print("Pipeline lefutott!")
        except Exception as e:
            print(f"Hiba a pipeline hívásakor: {e}")

    def record_microphone(self):
        try:
            mic = sc.default_microphone()
            with mic.recorder(samplerate=48000) as recorder, sf.SoundFile(self.mic_file, mode='w', samplerate=48000, channels=1) as file:
                while self.audio_threads_running:
                    data = recorder.record(numframes=24000)
                    if not self.is_paused:
                        file.write(data[:, 0])
        except: pass

    def record_game_audio(self):
        try:
            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(id=speaker.id, include_loopback=True)
            with loopback_mic.recorder(samplerate=48000) as recorder, sf.SoundFile(self.game_audio_file, mode='w', samplerate=48000, channels=2) as file:
                while self.audio_threads_running:
                    data = recorder.record(numframes=24000)
                    if not self.is_paused:
                        file.write(data)
        except: pass

    def matrix_to_euler(self, m):
        sy = math.sqrt(m[0][0] * m[0][0] + m[1][0] * m[1][0])
        if sy > 1e-6:
            x, y, z = math.atan2(m[2][1], m[2][2]), math.atan2(-m[2][0], sy), math.atan2(m[1][0], m[0][0])
        else:
            x, y, z = math.atan2(-m[1][2], m[1][1]), math.atan2(-m[2][0], sy), 0
        return [math.degrees(x), math.degrees(y), math.degrees(z)]

    def recording_loop(self):
        headers = ["Timestamp"]
        devices = ["HMD", "LeftCtrl", "RightCtrl"]
        last_screenshot_time = 0 
        
        for dev in devices:
            headers.extend([f"{dev}_PosX", f"{dev}_PosY", f"{dev}_PosZ", f"{dev}_RotX", f"{dev}_RotY", f"{dev}_RotZ", f"{dev}_LinVelX", f"{dev}_LinVelY", f"{dev}_LinVelZ", f"{dev}_AngVelX", f"{dev}_AngVelY", f"{dev}_AngVelZ"])
            if dev in ["LeftCtrl", "RightCtrl"]:
                headers.extend([f"{dev}_Trigger", f"{dev}_Grip", f"{dev}_JoyX", f"{dev}_JoyY"])
        headers.extend(["Eye_Gaze_X", "Eye_Gaze_Y", "Eye_Gaze_Z", "Pupil_Size_L", "Pupil_Size_R"]) 

        target_delay = 1.0 / self.sampling_rate

        with open(self.filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(headers)

            while self.is_recording:
                if self.is_paused:
                    time.sleep(0.1)
                    continue

                loop_start_time = time.time()
                current_time_obj = datetime.now()
                timestamp_str = current_time_obj.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                if loop_start_time - last_screenshot_time >= 1.0:
                    try:
                        vr_windows = gw.getWindowsWithTitle('VR View')
                        img = ImageGrab.grab(bbox=(vr_windows[0].left, vr_windows[0].top, vr_windows[0].right, vr_windows[0].bottom)) if vr_windows else ImageGrab.grab()
                        img_name = os.path.join(self.screenshot_dir, f"frame_{current_time_obj.strftime('%H%M%S')}.jpg")
                        threading.Thread(target=img.save, args=(img_name, "JPEG")).start()
                    except: pass
                    last_screenshot_time = loop_start_time
                
                poses = self.vr_system.getDeviceToAbsoluteTrackingPose(openvr.TrackingUniverseStanding, 0, openvr.k_unMaxTrackedDeviceCount)
                data_row = {col: 0.0 for col in headers}
                data_row["Timestamp"] = timestamp_str

                for i in range(openvr.k_unMaxTrackedDeviceCount):
                    if poses[i].bPoseIsValid:
                        device_class = self.vr_system.getTrackedDeviceClass(i)
                        prefix = "HMD" if device_class == openvr.TrackedDeviceClass_HMD else ("LeftCtrl" if self.vr_system.getControllerRoleForTrackedDeviceIndex(i) == openvr.TrackedControllerRole_LeftHand else ("RightCtrl" if self.vr_system.getControllerRoleForTrackedDeviceIndex(i) == openvr.TrackedControllerRole_RightHand else None))

                        if prefix:
                            matrix = poses[i].mDeviceToAbsoluteTracking
                            data_row[f"{prefix}_PosX"], data_row[f"{prefix}_PosY"], data_row[f"{prefix}_PosZ"] = matrix[0][3], matrix[1][3], matrix[2][3]
                            rot = self.matrix_to_euler(matrix)
                            data_row[f"{prefix}_RotX"], data_row[f"{prefix}_RotY"], data_row[f"{prefix}_RotZ"] = rot[0], rot[1], rot[2]
                            data_row[f"{prefix}_LinVelX"], data_row[f"{prefix}_LinVelY"], data_row[f"{prefix}_LinVelZ"] = poses[i].vVelocity[0], poses[i].vVelocity[1], poses[i].vVelocity[2]
                            data_row[f"{prefix}_AngVelX"], data_row[f"{prefix}_AngVelY"], data_row[f"{prefix}_AngVelZ"] = math.degrees(poses[i].vAngularVelocity[0]), math.degrees(poses[i].vAngularVelocity[1]), math.degrees(poses[i].vAngularVelocity[2])

                            if "Ctrl" in prefix:
                                result, pState = self.vr_system.getControllerState(i)
                                if result:
                                    data_row[f"{prefix}_JoyX"], data_row[f"{prefix}_JoyY"] = pState.rAxis[0].x, pState.rAxis[0].y
                                    data_row[f"{prefix}_Trigger"], data_row[f"{prefix}_Grip"] = pState.rAxis[1].x, pState.rAxis[2].x

                writer.writerow([data_row[col] for col in headers])
                file.flush()

                elapsed = time.time() - loop_start_time
                sleep_time = target_delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

vr_logger_instance = HeadlessVRLogger()