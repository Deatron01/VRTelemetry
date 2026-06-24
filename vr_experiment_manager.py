import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import uuid
from datetime import datetime, timezone

class VRExperimentManager:
    def __init__(self, root):
        self.root = root
        self.root.title("VR Telemetry - Kísérletvezérlő és Metaadat Kezelő")
        self.root.geometry("600x750")
        
        # --- IV. & V. TÁBLÁZAT: STATIKUS METAADATOK ÉS KALIBRÁCIÓ ---
        self.session_id = tk.StringVar(value=str(uuid.uuid4()))
        self.subject_id = tk.StringVar(value="SUBJ_001")
        
        self.age = tk.IntVar(value=24) 
        self.sex = tk.StringVar(value="Male")
        self.height = tk.DoubleVar(value=184.0)
        self.weight = tk.DoubleVar(value=115.0)
        self.ipd = tk.DoubleVar(value=64.0)
        self.dominant_hand = tk.StringVar(value="Right")
        self.vr_exp = tk.StringVar(value="Középhaladó")
        
        # --- VI. TÁBLÁZAT: SZUBJEKTÍV CÍMKÉK (SSQ & NASA-TLX) ---
        self.ssq_nausea = tk.DoubleVar(value=0.0)
        self.ssq_oculomotor = tk.DoubleVar(value=0.0)
        self.ssq_disorientation = tk.DoubleVar(value=0.0)
        
        self.nasa_mental = tk.IntVar(value=50)
        self.nasa_physical = tk.IntVar(value=50)
        self.nasa_frustration = tk.IntVar(value=50)
        self.session_rating = tk.IntVar(value=5)

        self._build_ui()

    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(pady=10, expand=True, fill='both')

        # 1. Tab: Pre-Session (Biometria és Kalibráció)
        frame_pre = ttk.Frame(notebook)
        notebook.add(frame_pre, text="1. Pre-Session (Mérés Előtt)")
        
        ttk.Label(frame_pre, text="Alany Életkora (év):").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        ttk.Entry(frame_pre, textvariable=self.age).grid(row=0, column=1, padx=10, pady=5)
        
        ttk.Label(frame_pre, text="Biológiai Nem:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        ttk.Combobox(frame_pre, textvariable=self.sex, values=["Male", "Female", "Other"]).grid(row=1, column=1, padx=10, pady=5)
        
        ttk.Label(frame_pre, text="Testmagasság (cm):").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        ttk.Entry(frame_pre, textvariable=self.height).grid(row=2, column=1, padx=10, pady=5)
        
        ttk.Label(frame_pre, text="Testsúly (kg):").grid(row=3, column=0, sticky="w", padx=10, pady=5)
        ttk.Entry(frame_pre, textvariable=self.weight).grid(row=3, column=1, padx=10, pady=5)
        
        ttk.Label(frame_pre, text="Domináns Kéz:").grid(row=4, column=0, sticky="w", padx=10, pady=5)
        ttk.Combobox(frame_pre, textvariable=self.dominant_hand, values=["Right", "Left"]).grid(row=4, column=1, padx=10, pady=5)

        # 2. Tab: Post-Session (Szubjektív Értékelés)
        frame_post = ttk.Frame(notebook)
        notebook.add(frame_post, text="2. Post-Session (Mérés Után)")
        
        ttk.Label(frame_post, text="SSQ Hányinger Pontszám:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        ttk.Entry(frame_post, textvariable=self.ssq_nausea).grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(frame_post, text="NASA-TLX Fizikai Terhelés (0-100):").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        ttk.Scale(frame_post, from_=0, to=100, variable=self.nasa_physical, orient="horizontal").grid(row=1, column=1, padx=10, pady=5)
        
        ttk.Label(frame_post, text="Általános Élmény (1-5):").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        ttk.Combobox(frame_post, textvariable=self.session_rating, values=[1,2,3,4,5]).grid(row=2, column=1, padx=10, pady=5)

        ttk.Button(self.root, text="Metaadatok Mentése (JSON)", command=self.save_metadata).pack(pady=20)

    def save_metadata(self):
        output_dir = f"Sessions/{self.session_id.get()}"
        os.makedirs(output_dir, exist_ok=True)
        
        metadata = {
            "M-IV_Static_Metadata": {
                "session_id": self.session_id.get(),
                "subject_id": self.subject_id.get(),
                "subject_age": self.age.get(),
                "subject_biological_sex": self.sex.get(),
                "subject_height_cm": self.height.get(),
                "subject_weight_kg": self.weight.get(),
                "subject_vr_exp": self.vr_exp.get()
            },
            "C-V_Calibration": {
                "dominant_hand": self.dominant_hand.get(),
                "subject_ipd_mm": self.ipd.get()
            },
            "Q-VI_Subjective_Labels": {
                "ssq_nausea_score": self.ssq_nausea.get(),
                "ssq_oculomotor_score": self.ssq_oculomotor.get(),
                "nasa_tlx_mental": self.nasa_mental.get(),
                "nasa_tlx_physical": self.nasa_physical.get(),
                "session_rating": self.session_rating.get()
            }
        }
        
        file_path = os.path.join(output_dir, "session_metadata.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)
            
        messagebox.showinfo("Siker", f"Metaadatok sikeresen elmentve!\nMappa: {output_dir}")

if __name__ == "__main__":
    root = tk.Tk()
    app = VRExperimentManager(root)
    root.mainloop()