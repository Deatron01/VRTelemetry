import React, { useState, useEffect } from 'react';
import { Activity, Map, Mic, Play, RefreshCw, ChevronRight, Square, Pause, Circle, Film, Cpu } from 'lucide-react'; // <--- ÚJ IKON: Cpu

const API_URL = "http://127.0.0.1:8000";

function App() {
  const [activeTab, setActiveTab] = useState('graphs');
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [sessionData, setSessionData] = useState(null);
  const [recordStatus, setRecordStatus] = useState({ is_recording: false, is_paused: false });
  
  const [maxFps, setMaxFps] = useState(90);
  const [samplingRate, setSamplingRate] = useState(90);
  const [heatmap2dIndex, setHeatmap2dIndex] = useState(0);

  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_URL}/api/sessions`);
      const data = await res.json();
      setSessions(data.sessions);
      if (data.sessions.length > 0 && !selectedSession) {
        setSelectedSession(data.sessions[0]);
      }
    } catch (err) { }
  };

  const fetchMaxFps = async () => {
    try {
      const res = await fetch(`${API_URL}/api/record/max-fps`);
      const data = await res.json();
      setMaxFps(data.max_fps);
      setSamplingRate(data.max_fps);
    } catch (err) { }
  };

  const fetchRecordStatus = async () => {
    try {
      const res = await fetch(`${API_URL}/api/record/status`);
      const data = await res.json();
      setRecordStatus(data);
    } catch (err) { }
  };

  useEffect(() => { 
    fetchSessions(); 
    fetchMaxFps();
    fetchRecordStatus();
    const interval = setInterval(fetchRecordStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!selectedSession) return;
    const fetchDetails = async () => {
      const res = await fetch(`${API_URL}/api/sessions/${selectedSession}`);
      const data = await res.json();
      setSessionData(data);
      setHeatmap2dIndex(0); 
    };
    fetchDetails();
  }, [selectedSession]);

  const handleRecordAction = async (action) => {
    try {
      const url = action === 'start' 
        ? `${API_URL}/api/record/start?sampling_rate=${samplingRate}`
        : `${API_URL}/api/record/${action}`;
        
      await fetch(url, { method: 'POST' });
      fetchRecordStatus();
      if (action === 'stop') setTimeout(fetchSessions, 2000);
    } catch (err) { }
  };

  // --- ÚJ: Metaadat kártya renderelő komponens ---
  const renderMetaSection = (title, data) => {
    if (!data) return null;
    return (
      <div className="glass-panel p-6 shadow-lg">
        <h3 className="text-lg font-medium mb-4 text-blue-300 border-b border-white/10 pb-2">{title}</h3>
        <div className="flex flex-col gap-3">
          {Object.entries(data).map(([key, val]) => (
            <div key={key} className="flex justify-between items-center text-sm">
              <span className="text-gray-400 font-medium">{key.replace(/_/g, ' ')}:</span>
              <span className="text-white font-mono bg-black/30 px-3 py-1 rounded shadow-inner max-w-[60%] truncate" title={String(val)}>
                {String(val)}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen p-6 md:p-8 flex flex-col gap-6">
      {/* FEJLÉC */}
      <header className="glass-panel p-4 flex justify-between items-center px-8">
        <h1 className="text-2xl font-light tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
          VR <span className="font-bold text-white">TELEMETRY</span>
        </h1>
        <div className="flex items-center gap-3 text-sm text-gray-400">
          <span className={`w-2 h-2 rounded-full ${recordStatus.is_recording ? 'bg-red-500 animate-pulse' : 'bg-emerald-400 animate-pulse'}`}></span>
          {recordStatus.is_recording ? 'Felvétel folyamatban...' : 'Backend API Online'}
        </div>
      </header>

      <div className="flex flex-col md:flex-row gap-6 h-[calc(100vh-140px)]">
        {/* BAL OLDALSÁV */}
        <aside className="glass-panel w-full md:w-1/4 p-6 flex flex-col gap-6">
          <div className="flex-1 overflow-y-auto custom-scrollbar">
            <h2 className="text-sm font-semibold tracking-wider text-gray-400 uppercase mb-4">Projektek</h2>
            <div className="flex flex-col gap-3"> 
              {sessions.map(session => (
                <button
                  key={session}
                  onClick={() => setSelectedSession(session)}
                  className={`w-full text-left px-5 py-4 rounded-xl transition-all duration-300 flex items-center justify-between group
                    ${selectedSession === session 
                      ? 'bg-blue-500/20 backdrop-blur-md border border-blue-400/40 text-white' 
                      : 'bg-white/5 hover:bg-white/15 backdrop-blur-md border border-white/10 text-gray-300 hover:text-white hover:border-white/20' 
                    }`}
                >
                  <span className="truncate text-sm font-medium tracking-wide">
                     {session.replace("Session_", "")}
                  </span>
                  <ChevronRight size={18} className={`transition-transform duration-300 ${selectedSession === session ? 'translate-x-1 text-blue-400' : 'opacity-50 group-hover:opacity-100'}`} />
                </button>
              ))}
            </div>
          </div>

          {/* FELVÉTEL VEZÉRLŐ PANEL */}
          <div className="mt-auto flex flex-col p-4 bg-black/20 rounded-xl border border-white/5 shadow-inner">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs font-bold tracking-wider text-gray-400 uppercase">VR Rögzítés</h3>
              <button onClick={fetchSessions} className="text-gray-400 hover:text-white transition-colors"><RefreshCw size={14} /></button>
            </div>
            
            {!recordStatus.is_recording ? (
              <>
                <div className="mb-4">
                  <div className="flex justify-between text-xs text-gray-400 mb-2">
                    <label>Mintavételezés (Sebesség)</label>
                    <span className="font-bold text-white">{samplingRate} Hz</span>
                  </div>
                  <input 
                    type="range" 
                    min="10" 
                    max={maxFps} 
                    value={samplingRate} 
                    onChange={(e) => setSamplingRate(parseInt(e.target.value))} 
                    className="w-full accent-red-500 cursor-pointer"
                  />
                </div>

                <button 
                  onClick={() => handleRecordAction('start')}
                  className="w-full py-3 rounded-xl bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white font-bold shadow-[0_0_15px_rgba(225,29,72,0.4)] transition-all flex items-center justify-center gap-2"
                >
                  <Circle size={16} fill="currentColor" /> REC
                </button>
              </>
            ) : (
              <>
                <div className="text-xs text-center text-red-400 animate-pulse font-medium mb-3">
                  {recordStatus.is_paused ? '⏸ Szüneteltetve' : `● Felvétel fut (${samplingRate}Hz)`}
                </div>
                <div className="flex gap-2">
                  <button onClick={() => handleRecordAction('pause')} className="flex-1 py-2 rounded-xl bg-amber-500/20 text-amber-400 border border-amber-500/50 hover:bg-amber-500/40 transition-all flex items-center justify-center">
                    {recordStatus.is_paused ? <Play size={16}/> : <Pause size={16}/>}
                  </button>
                  <button onClick={() => handleRecordAction('stop')} className="flex-[2] py-2 rounded-xl bg-red-500/20 text-red-400 border border-red-500/50 hover:bg-red-500/40 transition-all flex items-center justify-center gap-2 font-medium">
                    <Square size={16} fill="currentColor" /> Stop
                  </button>
                </div>
              </>
            )}
          </div>
        </aside>

        {/* FŐ TARTALOM */}
        <main className="glass-panel w-full md:w-3/4 p-6 flex flex-col">
          <div className="flex gap-2 p-1 bg-black/20 backdrop-blur-md rounded-2xl w-fit mb-6 border border-white/5 shadow-inner overflow-x-auto">
            {/* ÚJ: Metaadatok fül */}
            <TabButton active={activeTab === 'metadata'} onClick={() => setActiveTab('metadata')} icon={<Cpu size={18}/>} label="Metaadatok" />
            <div className="w-[1px] h-8 bg-white/10 mx-2 self-center"></div> {/* Elválasztó */}
            
            <TabButton active={activeTab === 'graphs'} onClick={() => setActiveTab('graphs')} icon={<Activity size={18}/>} label="Gráfok" />
            <TabButton active={activeTab === 'heatmap'} onClick={() => setActiveTab('heatmap')} icon={<Map size={18}/>} label="3D Heatmap" />
            <TabButton active={activeTab === 'heatmap2d'} onClick={() => setActiveTab('heatmap2d')} icon={<Film size={18}/>} label="2D Hőtérképek" />
            <TabButton active={activeTab === 'audio'} onClick={() => setActiveTab('audio')} icon={<Mic size={18}/>} label="Audio & Leirat" />
            <TabButton active={activeTab === 'playback'} onClick={() => setActiveTab('playback')} icon={<Play size={18}/>} label="Szimuláció" />
          </div>

          <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
            {!sessionData ? (
              <div className="text-gray-500 flex justify-center items-center h-full">Válassz ki egy projektet!</div>
            ) : (
              <>
                {/* 0. METAADATOK FÜL (ÚJ!) */}
                {activeTab === 'metadata' && (
                  <div className="flex flex-col gap-6">
                    {sessionData.metadata && Object.keys(sessionData.metadata).length > 0 ? (
                      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                        {renderMetaSection("Mérés Adatai", sessionData.metadata.Meres_Adatai)}
                        {renderMetaSection("VR Hardver Info", sessionData.metadata.VR_Hardver)}
                        {renderMetaSection("Operációs Rendszer", sessionData.metadata.Rendszer)}
                        {renderMetaSection("Hálózat és Környezet", sessionData.metadata.Felhasznalo_es_Halozat)}
                      </div>
                    ) : (
                      <div className="bg-black/40 rounded-xl border border-white/10 w-full min-h-[300px] flex items-center justify-center text-gray-500">
                        Nem találhatók metaadatok ehhez a méréshez (valószínűleg a frissítés előtt készült).
                      </div>
                    )}
                  </div>
                )}

                {/* 1. GRÁFOK FÜL */}
                {activeTab === 'graphs' && (
                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                    {sessionData.images?.map((img, i) => (
                      <div key={i} className="bg-black/30 rounded-xl overflow-hidden border border-white/5 relative group shadow-lg">
                        <img src={img.url} alt={img.title} className="w-full h-auto" />
                      </div>
                    ))}
                  </div>
                )}

                {/* 2. 3D HEATMAP FÜL */}
                {activeTab === 'heatmap' && (
                  <div className="w-full h-full min-h-[600px] bg-black/40 rounded-xl border border-white/10 overflow-hidden shadow-lg">
                    {sessionData.heatmap_url ? <iframe src={sessionData.heatmap_url} className="w-full h-full border-none" /> : <p className="p-6 text-gray-500">Nincs 3D Heatmap.</p>}
                  </div>
                )}

                {/* 3. 2D HŐTÉRKÉP FÜL */}
                {activeTab === 'heatmap2d' && (
                  <div className="w-full h-full flex flex-col gap-4 min-h-[600px]">
                    {sessionData.heatmaps_2d && sessionData.heatmaps_2d.length > 0 ? (
                      <>
                        <div className="flex-1 bg-black/40 rounded-xl border border-white/10 flex items-center justify-center overflow-hidden shadow-lg p-2">
                          <img src={sessionData.heatmaps_2d[heatmap2dIndex]} className="max-h-[500px] w-auto rounded-lg object-contain" alt="2D Hőtérkép" />
                        </div>
                        <div className="glass-panel p-4 flex items-center gap-4">
                          <button onClick={() => setHeatmap2dIndex(i => Math.max(0, i - 1))} className="glass-button px-4 py-2 font-bold text-white hover:text-blue-400">&lt; Előző</button>
                          <input 
                            type="range" 
                            min="0" 
                            max={sessionData.heatmaps_2d.length - 1} 
                            value={heatmap2dIndex} 
                            onChange={(e) => setHeatmap2dIndex(parseInt(e.target.value))} 
                            className="flex-1 accent-blue-500 cursor-pointer" 
                          />
                          <button onClick={() => setHeatmap2dIndex(i => Math.min(sessionData.heatmaps_2d.length - 1, i + 1))} className="glass-button px-4 py-2 font-bold text-white hover:text-blue-400">Következő &gt;</button>
                          <span className="text-gray-400 font-mono w-16 text-right">{heatmap2dIndex + 1} / {sessionData.heatmaps_2d.length}</span>
                        </div>
                      </>
                    ) : (
                      <div className="bg-black/40 rounded-xl border border-white/10 w-full h-full flex items-center justify-center text-gray-500">
                        Nem készültek 2D hőtérképek ehhez a méréshez.
                      </div>
                    )}
                  </div>
                )}

                {/* 4. AUDIO FÜL */}
                {activeTab === 'audio' && (
                  <div className="flex flex-col gap-6">
                    <div className="glass-panel p-6">
                      <h3 className="text-lg font-medium mb-4 text-gray-200">Whisper AI Leirat</h3>
                      <div className="bg-black/40 rounded-xl p-5 h-64 overflow-y-auto font-mono text-sm text-gray-300 border border-white/5 whitespace-pre-wrap">{sessionData.transcript}</div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="glass-panel p-6">
                        <h4 className="text-sm text-gray-400 mb-3 flex items-center gap-2"><Mic size={16} /> Mikrofon</h4>
                        {sessionData.mic_url ? <audio src={sessionData.mic_url} className="w-full" controls /> : <p className="text-gray-600">Nincs fájl.</p>}
                      </div>
                      <div className="glass-panel p-6">
                        <h4 className="text-sm text-gray-400 mb-3 flex items-center gap-2"><Play size={16} /> Játék Hang</h4>
                        {sessionData.game_url ? <audio src={sessionData.game_url} className="w-full" controls /> : <p className="text-gray-600">Nincs fájl.</p>}
                      </div>
                    </div>
                  </div>
                )}

                {/* 5. PLAYBACK FÜL */}
                {activeTab === 'playback' && (
                  <div className="w-full h-full min-h-[600px] bg-black/40 rounded-xl border border-white/10 overflow-hidden shadow-lg">
                    {sessionData.playback_url ? <iframe src={sessionData.playback_url} className="w-full h-full border-none" /> : <p className="p-6 text-gray-500">Nincs szimuláció.</p>}
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

function TabButton({ active, onClick, icon, label }) {
  return (
    <button onClick={onClick} className={`flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-all duration-300 whitespace-nowrap
      ${active ? 'bg-white/10 text-white shadow-[0_4px_12px_rgba(0,0,0,0.1)] border border-white/10' : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'}`}>
      {icon}<span>{label}</span>
    </button>
  );
}
export default App;