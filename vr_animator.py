import sys
import os
from turtle import color
import pandas as pd
import json
import tkinter as tk
from tkinter import filedialog
sys.stdout.reconfigure(encoding='utf-8')
def generate_playback_html(session_dir):
    csv_file = os.path.join(session_dir, "telemetry.csv")
    if not os.path.exists(csv_file):
        print(f"Hiba: Nem található {csv_file}")
        return

    print(f"Visszajátszás generálása a következő mappához: {session_dir}...")
    df = pd.read_csv(csv_file)
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    df['Time_Sec'] = (df['Timestamp'] - df['Timestamp'].iloc[0]).dt.total_seconds()

    # Optimalizálás: Ha túl sok az adat, ritkítjuk
    step = max(1, len(df) // 1000)
    df_sampled = df.iloc[::step].copy()

    # Adatok JSON formátumra alakítása
    frames = []
    for _, row in df_sampled.iterrows():
        frames.append({
            'time': round(row['Time_Sec'], 2),
            'head': {
                'pos': [row['HMD_PosX'], row['HMD_PosY'], row['HMD_PosZ']],
                'rot': [row['HMD_RotX'], row['HMD_RotY'], row['HMD_RotZ']]
            },
            'left': {
                'pos': [row['LeftCtrl_PosX'], row['LeftCtrl_PosY'], row['LeftCtrl_PosZ']],
                'rot': [row['LeftCtrl_RotX'], row['LeftCtrl_RotY'], row['LeftCtrl_RotZ']]
            },
            'right': {
                'pos': [row['RightCtrl_PosX'], row['RightCtrl_PosY'], row['RightCtrl_PosZ']],
                'rot': [row['RightCtrl_RotX'], row['RightCtrl_RotY'], row['RightCtrl_RotZ']]
            }
        })

    frames_json = json.dumps(frames)
    
    # HTML Sablon a Three.js-el
    html_content = f"""
    <!DOCTYPE html>
    <html lang="hu">
    <head>
        <meta charset="UTF-8">
        <title>VR 3D Visszajátszás</title>
        <style>
            body {{ margin: 0; overflow: hidden; background-color: #0E1117; color: white; font-family: sans-serif; }}
            #ui-container {{ position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%); width: 80%; background: rgba(0, 0, 0, 0.7); padding: 15px 25px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); backdrop-filter: blur(10px); display: flex; align-items: center; gap: 15px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
            #play-btn {{ background: #3b82f6; border: none; color: white; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: bold; width: 80px; }}
            #play-btn:hover {{ background: #2563eb; }}
            #timeline {{ flex-grow: 1; cursor: pointer; accent-color: #3b82f6; }}
            #time-display {{ font-family: monospace; font-size: 14px; width: 60px; text-align: right; }}
            .info-panel {{ position: absolute; top: 20px; left: 20px; background: rgba(0,0,0,0.5); padding: 10px; border-radius: 8px; font-size: 12px; color: #aaa; pointer-events: none; border: 1px solid rgba(255,255,255,0.05); }}
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div class="info-panel">
            <b>Irányítás:</b><br>Bal egérgomb: Forgatás<br>Jobb egérgomb: Tolás<br>Görgő: Zoom
        </div>

       <div id="ui-container">
            <button id="play-btn">▶ Play</button>
            <input type="range" id="timeline" min="0" max="{len(frames)-1}" value="0">
            <span id="time-display">0.00s</span>
            
            <select id="speed-select">
                <option value="0.1">0.1x</option>
                <option value="0.2">0.2x</option>
                <option value="0.5">0.5x</option>
                <option value="0.8">0.8x</option>
                <option value="1" selected>1.0x</option>
                <option value="1.2">1.2x</option>
                <option value="1.5">1.5x</option>
                <option value="1.8">1.8x</option>
                <option value="2">2x</option>
                <option value="4">4x</option>
                <option value="8">8x</option>
                <option value="16">16x</option>
            </select>
        </div>

        <script>
            const frames = {frames_json};
            const totalFrames = frames.length;
            
            const scene = new THREE.Scene();
            scene.background = new THREE.Color('#0E1117');
            scene.fog = new THREE.Fog('#0E1117', 2, 10);

            const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 100);
            camera.position.set(0, 2, 3);

            const renderer = new THREE.WebGLRenderer({{ antialias: true }});
            renderer.setSize(window.innerWidth, window.innerHeight);
            document.body.appendChild(renderer.domElement);

            const controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.target.set(0, 1.5, 0);
            controls.update();

            const gridHelper = new THREE.GridHelper(10, 20, 0x444444, 0x222222);
            scene.add(gridHelper);

            const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
            scene.add(ambientLight);
            const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
            dirLight.position.set(2, 5, 2);
            scene.add(dirLight);

            // Fej (HMD)
            const headGeo = new THREE.BoxGeometry(0.2, 0.12, 0.15);
            const headMat = new THREE.MeshPhongMaterial({{ color: 0x00ffff, transparent: true, opacity: 0.8 }});
            const head = new THREE.Mesh(headGeo, headMat);

            // [Javítás] Szemellenző (Visor) - Ez az eleje!
            const visorGeo = new THREE.BoxGeometry(0.18, 0.05, 0.02);
            const visorMat = new THREE.MeshBasicMaterial({{ color: 0xffffff }}); // Fehér, hogy jól látszódjon
            const visor = new THREE.Mesh(visorGeo, visorMat);
            visor.position.z = -0.075; // A doboz elülső lapjára tesszük
            head.add(visor);

            // [ÚJ] Irányjelző pont (Hogy még egyértelműbb legyen)
            const pointerGeo = new THREE.ConeGeometry(0.02, 0.05, 4);
            const pointerMat = new THREE.MeshBasicMaterial({{ color: 0xff0000 }}); // Piros nyíl
            const pointer = new THREE.Mesh(pointerGeo, pointerMat);
            pointer.rotation.x = Math.PI / 2;
            pointer.position.z = -0.09; 
            head.add(pointer);

            scene.add(head);
            
            const handGeo = new THREE.BoxGeometry(0.08, 0.08, 0.15);
            const leftMat = new THREE.MeshPhongMaterial({{ color: 0xff4444 }});
            const leftHand = new THREE.Mesh(handGeo, leftMat);
            scene.add(leftHand);

            const rightMat = new THREE.MeshPhongMaterial({{ color: 0x44ff44 }});
            const rightHand = new THREE.Mesh(handGeo, rightMat);
            scene.add(rightHand);

            const lineMat = new THREE.LineBasicMaterial({{ color: 0x888888, transparent: true, opacity: 0.5 }});
            const leftArmGeo = new THREE.BufferGeometry();
            const rightArmGeo = new THREE.BufferGeometry();
            const leftArm = new THREE.Line(leftArmGeo, lineMat);
            const rightArm = new THREE.Line(rightArmGeo, lineMat);
            scene.add(leftArm);
            scene.add(rightArm);

           
            let currentFrameIndex = 0;
            let isPlaying = false;
            let timeScale = 1.0;
            let lastTime = 0;
            let currentPlaybackTime = 0;

            const slider = document.getElementById('timeline');
            const playBtn = document.getElementById('play-btn');
            const timeDisplay = document.getElementById('time-display');
            const speedSelect = document.getElementById('speed-select');

            // Sebesség váltás
            speedSelect.addEventListener('change', (e) => {{
                timeScale = parseFloat(e.target.value);
            }});

            function loop(timestamp) {{
                if (isPlaying) {{
                    if (lastTime === 0) lastTime = timestamp;
                    
                    // Mennyi idő telt el az előző frame óta (ms-ben)
                    const deltaTime = (timestamp - lastTime) * timeScale;
                    lastTime = timestamp;
                    
                    // Növeljük a lejátszási időt
                    currentPlaybackTime += deltaTime / 1000; // másodpercben
                    
                    // Megkeressük a legközelebbi képkockát az időhöz
                    // A 'frames' tömbben lévő 'time' értékek alapján
                    let newIndex = 0;
                    for (let i = 0; i < totalFrames; i++) {{
                        if (frames[i].time >= currentPlaybackTime) {{
                            newIndex = i;
                            break;
                        }}
                        newIndex = i;
                    }}
                    
                    if (newIndex >= totalFrames - 1) {{
                        currentPlaybackTime = 0; // Újrakezdés
                        newIndex = 0;
                    }}
                    
                    currentFrameIndex = newIndex;
                    applyFrame(currentFrameIndex);
                }} else {{
                    lastTime = 0; // Reset ha megállítjuk
                }}
                
                controls.update();
                renderer.render(scene, camera);
                requestAnimationFrame(() => loop(performance.now()));
            }}

            function applyFrame(index) {{
                if (index < 0 || index >= totalFrames) return;
                const f = frames[index];
                
                // Pozíciók
                head.position.set(f.head.pos[0], f.head.pos[1], -f.head.pos[2]); 
                leftHand.position.set(f.left.pos[0], f.left.pos[1], -f.left.pos[2]);
                rightHand.position.set(f.right.pos[0], f.right.pos[1], -f.right.pos[2]);

                // 1. Fej forgatása (YXZ sorrend + 90 fokos korrekció)
                const euler = new THREE.Euler(
                    f.head.rot[0] * Math.PI / 180, 
                    f.head.rot[1] * Math.PI / 180, 
                    f.head.rot[2] * Math.PI / 180, 
                    'YXZ'
                );
                
                // Létrehozzuk a forgatást
                const quat = new THREE.Quaternion().setFromEuler(euler);
                
                // 2. A 90 fokos eltolás alkalmazása (Y tengely körüli forgatás)
                // Ha 90 fokkal "arrébb van", akkor itt kell korrigálni:
                const offsetQuat = new THREE.Quaternion().setFromAxisAngle(
                    new THREE.Vector3(0, 1, 0), 
                    -Math.PI / 2  // Ha ez rossz irányba forgat, írd át +Math.PI / 2 -re
                );
                
                // Összeszorozzuk az eredeti forgatást a 90 fokos eltolással
                quat.multiply(offsetQuat);
                head.quaternion.copy(quat);
                
                // 3. Kezek forgatása (szintén YXZ sorrendben, hogy konzisztens legyen)
                const leftEuler = new THREE.Euler(f.left.rot[0] * Math.PI/180, f.left.rot[1] * Math.PI/180, f.left.rot[2] * Math.PI/180, 'YXZ');
                const rightEuler = new THREE.Euler(f.right.rot[0] * Math.PI/180, f.right.rot[1] * Math.PI/180, f.right.rot[2] * Math.PI/180, 'YXZ');
                
                leftHand.quaternion.setFromEuler(leftEuler);
                rightHand.quaternion.setFromEuler(rightEuler);
                
                // Karok frissítése
                leftArmGeo.setFromPoints([head.position.clone().setY(head.position.y - 0.2), leftHand.position]);
                rightArmGeo.setFromPoints([head.position.clone().setY(head.position.y - 0.2), rightHand.position]);

                slider.value = index;
                timeDisplay.innerText = f.time.toFixed(1) + "s";
            }}
            
            playBtn.addEventListener('click', () => {{
                isPlaying = !isPlaying;
                playBtn.innerText = isPlaying ? "⏸ Pause" : "▶ Play";
                if (!isPlaying) lastTime = 0;
            }});

            slider.addEventListener('input', (e) => {{
                isPlaying = false;
                playBtn.innerText = "▶ Play";
                currentFrameIndex = parseInt(e.target.value);
                applyFrame(currentFrameIndex);
            }});

            applyFrame(0);
            loop();

            window.addEventListener('resize', () => {{
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            }});
        </script>
    </body>
    </html>
    """

    out_file = os.path.join(session_dir, "vr_playback.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✅ Visszajátszás generálva: {out_file}")

# ==========================================
# AUTOMATIKUS MAPPAVÁLASZTÓ LOGIKA
# ==========================================
if __name__ == "__main__":
    # Ha a Mester Script (run_pipeline.py) indítja, megkapja a mappát argumentumként
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        # Ha kézzel indítod (paraméter nélkül), felugrik a választó ablak
        print("Mappaválasztó megnyitása...")
        root = tk.Tk()
        root.withdraw() # Elrejtjük a felesleges kis szürke Tkinter ablakot
        
        # Alapértelmezett mappa beállítása a Sessions-re, ha létezik
        init_dir = "Sessions" if os.path.exists("Sessions") else os.getcwd()
        
        target_dir = filedialog.askdirectory(title="Válaszd ki a Session mappát a Visszajátszáshoz", initialdir=init_dir)
        
        if not target_dir:
            print("Nem választottál mappát. Kilépés.")
            sys.exit(0)
            
    generate_playback_html(target_dir)