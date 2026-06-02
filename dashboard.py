import gradio as gr
import pandas as pd
import os
import subprocess

# ==========================================
# 1. ADATKEZELŐ FÜGGVÉNYEK
# ==========================================
def get_sessions():
    sessions_dir = "Sessions"
    if not os.path.exists(sessions_dir):
        os.makedirs(sessions_dir)
    sessions = [d for d in os.listdir(sessions_dir) if os.path.isdir(os.path.join(sessions_dir, d))]
    sessions.sort(reverse=True)
    return sessions

def launch_pipeline():
    print("Mérés és feldolgozás indítása...")
    # Futtatjuk a pipeline-t, és megvárjuk amíg befejeződik
    subprocess.run(["python", "run_pipeline.py"])
    print("Mérés befejezve!")
    # Frissítjük a lenyíló menüt az új méréssel
    return gr.Dropdown(choices=get_sessions())

def load_session_data(session_name):
    """Betölti a kiválasztott mérés adatait a UI komponensekbe."""
    if not session_name or session_name == "Nincs kiválasztva":
        return pd.DataFrame(), [], "<p style='color:gray;'>Válassz ki egy mérést a betöltéshez.</p>", "", None, None
        
    session_path = os.path.join("Sessions", session_name)
    
    # 1. CSV Adatok betöltése
    csv_path = os.path.join(session_path, "telemetry.csv")
    df = pd.DataFrame()
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        
    # 2. Generált képek (Graphs) betöltése
    graphs_dir = os.path.join(session_path, "graphs")
    images = []
    if os.path.exists(graphs_dir):
        # Összeszedjük és sorba rendezzük a png fájlokat
        images = [os.path.join(graphs_dir, f) for f in sorted(os.listdir(graphs_dir)) if f.endswith(".png")]
    elif os.path.exists(os.path.join(session_path, "qa_dashboard_results.png")):
        # Kompatibilitás a régi mérésekkel
        images = [os.path.join(session_path, "qa_dashboard_results.png")]
        
    # 3. 3D Heatmap HTML betöltése
    html_path = os.path.join(session_path, "vr_3d_heatmap.html")
    html_content = "<p style='color:gray;'>A 3D Heatmap nem található ehhez a méréshez.</p>"
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            raw_html = f.read()
        # Beágyazzuk egy méretezett iframe-be, hogy tökéletesen mutasson
        html_content = f'<iframe style="width: 100%; height: 750px; border: none; border-radius: 8px;" srcdoc="{raw_html.replace("\"", "&quot;")}"></iframe>'
        
    # 4. Whisper Transcript betöltése
    transcript_path = os.path.join(session_path, "transcript.txt")
    transcript = "Nem készült hang leirat (transcript.txt nem található)."
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = f.read()
            
    # 5. Audio fájlok
    mic_path = os.path.join(session_path, "audio_microphone.wav")
    game_path = os.path.join(session_path, "audio_stereo_game.wav")
    mic_audio = mic_path if os.path.exists(mic_path) else None
    game_audio = game_path if os.path.exists(game_path) else None
    
    return df, images, html_content, transcript, mic_audio, game_audio

# ==========================================
# 2. FELHASZNÁLÓI FELÜLET (UI) FELÉPÍTÉSE
# ==========================================
with gr.Blocks(title="VR Telemetry") as demo:
    gr.Markdown("# 🕶️ VR Telemetry Dashboard")
    
    with gr.Row():
        # --- BAL OLDALSÁV (Vezérlés) ---
        with gr.Column(scale=1, variant="panel"):
            gr.Markdown("### 🗂️ Mérések Kezelése")
            
            session_dropdown = gr.Dropdown(
                choices=get_sessions(), 
                label="Betöltendő mérés", 
                info="Válaszd ki a projektet a lenyíló menüből."
            )
            
            refresh_btn = gr.Button("🔄 Lista frissítése", size="sm")
            
            gr.Markdown("---")
            start_btn = gr.Button("🚀 ÚJ MÉRÉS INDÍTÁSA", variant="primary")
            
        # --- JOBB OLDAL (Tartalom megjelenítés) ---
        with gr.Column(scale=4):
            with gr.Tabs():
                
                # 1. FÜL: Grafikonok
                with gr.TabItem("📈 Gráfok & Adatok"):
                    gallery_view = gr.Gallery(label="Analitikai Ábrák", columns=2, height="auto", object_fit="contain")
                    with gr.Accordion("Nyers CSV Adatok megtekintése", open=False):
                        df_view = gr.Dataframe(label="Telemetria", max_height=300)
                    
                # 2. FÜL: 3D Heatmap
                with gr.TabItem("🗺️ 3D Heatmap"):
                    gr.Markdown("*Tipp: Használd az egeret a 3D modell forgatásához és nagyításához!*")
                    html_view = gr.HTML(label="3D Interaktív Tér")
                    
                # 3. FÜL: Audio
                with gr.TabItem("🎙️ Audio & Transcript"):
                    transcript_view = gr.Textbox(label="📝 Szöveges leirat (Whisper AI)", lines=12, interactive=False)
                    with gr.Row():
                        mic_view = gr.Audio(label="Mikrofon bemenet", type="filepath", interactive=False)
                        game_view = gr.Audio(label="Játék / Rendszer hangja", type="filepath", interactive=False)
                        
    # ==========================================
    # 3. INTERAKCIÓK ÖSSZEKÖTÉSE
    # ==========================================
    # Ha a legördülő menüben mérést váltasz, betölti az összes adatot:
    session_dropdown.change(
        fn=load_session_data, 
        inputs=[session_dropdown], 
        outputs=[df_view, gallery_view, html_view, transcript_view, mic_view, game_view]
    )
    
    # Gombok funkciói
    refresh_btn.click(fn=lambda: gr.Dropdown(choices=get_sessions()), outputs=[session_dropdown])
    start_btn.click(fn=launch_pipeline, outputs=[session_dropdown])

# ==========================================
# ALKALMAZÁS INDÍTÁSA
# ==========================================
if __name__ == "__main__":
    demo.launch(inbrowser=True, theme=gr.themes.Monochrome())