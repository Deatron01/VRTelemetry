import streamlit as st
import pandas as pd
import os
import plotly.express as px
import streamlit.components.v1 as components
import subprocess

# --- Ablak és Design Beállítások ---
st.set_page_config(page_title="VR Telemetry", layout="wide", initial_sidebar_state="expanded")

# Minimalista egyedi CSS beillesztése
st.markdown("""
    <style>
    .main { background-color: #0E1117; }
    h1, h2, h3 { font-weight: 300; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: transparent; border-radius: 4px; font-size: 16px; }
    </style>
""", unsafe_allow_html=True)

st.title("🕶️ VR Telemetry Dashboard")

# --- Oldalsáv: Mérések kezelése ---
st.sidebar.header("Mérések")
sessions_dir = "Sessions"

if not os.path.exists(sessions_dir):
    os.makedirs(sessions_dir)

# Session mappák beolvasása és rendezése (legújabb legfelül)
sessions = [d for d in os.listdir(sessions_dir) if os.path.isdir(os.path.join(sessions_dir, d))]
sessions.sort(reverse=True)

selected_session = st.sidebar.selectbox("Válaszd ki a betöltendő mérést:", ["Nincs kiválasztva"] + sessions)

st.sidebar.markdown("---")

# Új mérés indítása
if st.sidebar.button("🚀 Új mérés indítása", use_container_width=True):
    with st.spinner("Mérés folyamatban... Várd meg a végét!"):
        # Itt hívjuk meg a meglévő pipeline-t
        subprocess.run(["python", "run_pipeline.py"])
    st.success("Mérés és feldolgozás befejezve!")
    st.rerun()  # Frissíti a felületet az új méréssel

# --- Fő tartalom megjelenítése ---
if selected_session != "Nincs kiválasztva":
    session_path = os.path.join(sessions_dir, selected_session)
    st.subheader(f"Betöltött projekt: {selected_session}")
    
    # Fülek (Tabs) létrehozása a letisztultság érdekében
    tab_graphs, tab_heatmap, tab_audio = st.tabs(["📈 Gráfok & Adatok", "🗺️ 3D Heatmap", "🎙️ Audio & Transcript"])
    
    # --- 1. FÜL: Gráfok és Telemetria ---
    with tab_graphs:
        csv_path = os.path.join(session_path, "telemetry.csv")
        qa_img = os.path.join(session_path, "qa_dashboard_results.png")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                
                # Egy interaktív Plotly gráf példa (ha van time és fps oszlop)
                # Ezt a CSV-d valós oszlopaihoz kell igazítani!
                if len(df.columns) >= 2:
                    x_col = df.columns[0]  # pl. timestamp
                    y_col = df.columns[1]  # pl. value
                    fig = px.line(df, x=x_col, y=y_col, title="Fő metrika alakulása", template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)
                
                with st.expander("Nyers CSV adatok megtekintése"):
                    st.dataframe(df, use_container_width=True)
            else:
                st.info("Nem található telemetry.csv az adott méréshez.")
                
        with col2:
            if os.path.exists(qa_img):
                st.image(qa_img, caption="QA Dashboard statikus eredmények", use_container_width=True)
            else:
                st.info("Nincs elérhető QA Dashboard kép.")

    # --- 2. FÜL: 3D Heatmap ---
    with tab_heatmap:
        html_path = os.path.join(session_path, "vr_3d_heatmap.html")
        if os.path.exists(html_path):
            with open(html_path, 'r', encoding='utf-8') as f:
                html_data = f.read()
            # Interaktív HTML beágyazása
            components.html(html_data, height=700, scrolling=True)
        else:
            st.info("A 3D Heatmap (vr_3d_heatmap.html) még nem generálódott le ehhez a méréshez.")

    # --- 3. FÜL: Audio és Transcript ---
    with tab_audio:
        transcript_path = os.path.join(session_path, "transcript.txt")
        if os.path.exists(transcript_path):
            with open(transcript_path, 'r', encoding='utf-8') as f:
                transcript_text = f.read()
            st.markdown("### 📝 Szöveges leirat")
            st.text_area(label="", value=transcript_text, height=300, disabled=True)
        else:
            st.info("Nem található transcript.txt.")
            
        st.markdown("---")
        st.markdown("### 🎧 Hanganyagok")
        col_mic, col_game = st.columns(2)
        
        with col_mic:
            st.markdown("**Mikrofon bemenet**")
            mic_path = os.path.join(session_path, "audio_microphone.wav")
            if os.path.exists(mic_path):
                st.audio(mic_path)
            else:
                st.warning("Nincs mikrofon felvétel.")
                
        with col_game:
            st.markdown("**Játék / Rendszer hangja**")
            game_path = os.path.join(session_path, "audio_stereo_game.wav")
            if os.path.exists(game_path):
                st.audio(game_path)
            else:
                st.warning("Nincs játék hang felvétel.")

else:
    st.write("⬅️ **Kérlek, válassz egy korábbi mérést a bal oldali sávból, vagy indíts el egy újat.**")