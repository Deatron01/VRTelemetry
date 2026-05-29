import os
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
sys.stdout.reconfigure(encoding='utf-8')
def main():
    print("VR QA Automata Feldolgozó Rendszer")
    print("=" * 50)
    
    # 1. Mappa kiválasztása
    root = tk.Tk()
    root.withdraw()
    
    # Létrehozzuk a Sessions mappát, ha még nem létezne
    os.makedirs("Sessions", exist_ok=True)
    
    if len(sys.argv) > 1:
        session_dir = sys.argv[1]
        print(f"Automatikus indítás a Loggerből: {session_dir}")
    else:
        root = tk.Tk()
        root.withdraw()
        session_dir = filedialog.askdirectory(title="Válaszd ki a feldolgozni kívánt Session mappát", initialdir="Sessions")

    if not session_dir:
        print("Nem választottál mappát. Kilépés.")
        return

    print(f"\n[+] FELDOLGOZÁS INDÍTÁSA: {os.path.basename(session_dir)}\n")
    # 2. A lefuttatandó elemző scriptek listája
    # Formátum: ("Folyamat neve a konzolban", "python_fajlneve.py")
    scripts_to_run = [
        ("Műszerfal (Dashboard) Generálása", "vr_analyzer.py"),
        ("Térbeli 3D Hőtérkép Generálása", "vr_3d_heatmap.py"),
        ("2D Képernyő Hőtérképek (Pillanatképek)", "vr_heatmap_generator.py"),
        ("Beszéd-Szöveg átirat (Whisper AI)", "vr_transcriber.py")
    ]

    # 3. Scriptek sorozatos futtatása
    for description, script_name in scripts_to_run:
        if os.path.exists(script_name):
            print(f"[*] Futtatás: {description} ({script_name})...")
            try:
                # A subprocess úgy hívja meg a másik python scriptet, 
                # mintha a terminálba írnád: python script.py "Sessions/Mappa_Neve"
                subprocess.run([sys.executable, script_name, session_dir], check=True)
                print(f"    -> [SIKER] Kész!\n")
            except subprocess.CalledProcessError as e:
                print(f"    -> [HIBA] A script leállt: {e}\n")
        else:
            print(f"    -> [UGRÁS] A '{script_name}' nem található a főkönyvtárban.\n")

    print("=" * 50)
    print("MINDEN FELDOLGOZÁS BEFEJEZŐDÖTT!")
    
    # Kész ablak, hogy vizuálisan is jelezze a végét
    messagebox.showinfo(
        "Feldolgozás Kész", 
        f"A mérés minden adatát sikeresen feldolgoztuk!\n\nAz eredmények (Képek, HTML fájlok, Műszerfal) mind megtalálhatóak a\n'{os.path.basename(session_dir)}' mappában."
    )
    
    # Opcionális: A rendszer meg is nyithatja a mappát a végén!
    os.startfile(session_dir)

if __name__ == "__main__":
    main()