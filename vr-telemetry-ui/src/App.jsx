import React, { useState, useEffect } from 'react';
import { Activity, Map, Mic, Play, RefreshCw, ChevronRight } from 'lucide-react';

const API_URL = "http://localhost:8000";

function App() {
  const [activeTab, setActiveTab] = useState('graphs');
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [sessionData, setSessionData] = useState(null);
  const [loading, setLoading] = useState(false);

  // 1. Mérések lekérése induláskor
  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_URL}/api/sessions`);
      const data = await res.json();
      setSessions(data.sessions);
      if (data.sessions.length > 0 && !selectedSession) {
        setSelectedSession(data.sessions[0]);
      }
    } catch (err) {
      console.error("Nem sikerült elérni a Python szervert!", err);
    }
  };

  useEffect(() => { fetchSessions(); }, []);

  // 2. Kiválasztott mérés adatainak lekérése
  useEffect(() => {
    if (!selectedSession) return;
    const fetchDetails = async () => {
      const res = await fetch(`${API_URL}/api/sessions/${selectedSession}`);
      const data = await res.json();
      setSessionData(data);
    };
    fetchDetails();
  }, [selectedSession]);

  // 3. Pipeline indítása gombra
  const handleRunPipeline = async () => {
    setLoading(true);
    await fetch(`${API_URL}/api/run-pipeline`, { method: 'POST' });
    await fetchSessions();
    setLoading(false);
  };

  return (
    <div className="min-h-screen p-6 md:p-8 flex flex-col gap-6">
      {/* FEJLÉC */}
      <header className="glass-panel p-4 flex justify-between items-center px-8">
        <h1 className="text-2xl font-light tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
          VR <span className="font-bold text-white">TELEMETRY</span>
        </h1>
        <div className="flex items-center gap-3 text-sm text-gray-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          Backend API Online
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
                  // Frissített stílusok: Nincs glow, nincs scale, csak kék üveghatás
                  className={`w-full text-left px-5 py-4 rounded-xl transition-all duration-300 flex items-center justify-between group
                    ${selectedSession === session 
                      ? 'bg-blue-500/20 backdrop-blur-md border border-blue-400/40 text-white' // Aktív: Kékre színezett üveg
                      : 'bg-white/5 hover:bg-white/15 backdrop-blur-md border border-white/10 text-gray-300 hover:text-white hover:border-white/20' // Inaktív
                    }`}
                >
                  <span className="truncate text-sm font-medium tracking-wide">
                     {session.replace("Session_", "")}
                  </span>
                  <ChevronRight size={18} className={`transition-transform duration-300 ${selectedSession === session ? 'translate-x-1 text-blue-400' : 'opacity-50 group-hover:opacity-100'}`} />
                </button>
              ))}
              {sessions.length === 0 && (
                <div className="text-gray-500 text-sm text-center py-4">
                  Még nincsenek projektek.
                </div>
              )}
            </div>
          </div>

          <div className="mt-auto flex flex-col gap-3">
            <button onClick={fetchSessions} className="glass-button w-full py-3 flex items-center justify-center gap-2 text-gray-300 hover:text-white">
              <RefreshCw size={18} />
              <span className="text-sm">Lista Frissítése</span>
            </button>
            <button 
              onClick={handleRunPipeline}
              disabled={loading}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium shadow-[0_0_20px_rgba(79,70,229,0.4)] transition-all flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {loading ? <RefreshCw size={18} className="animate-spin" /> : <Play size={18} fill="currentColor" />}
              {loading ? 'FELDOLGOZÁS...' : 'ÚJ MÉRÉS INDÍTÁSA'}
            </button>
          </div>
        </aside>

        {/* FŐ TARTALOM */}
        <main className="glass-panel w-full md:w-3/4 p-6 flex flex-col">
          {/* FÜLEK */}
          <div className="flex gap-2 p-1 bg-black/20 backdrop-blur-md rounded-2xl w-fit mb-6 border border-white/5 shadow-inner">
            <TabButton active={activeTab === 'graphs'} onClick={() => setActiveTab('graphs')} icon={<Activity size={18}/>} label="Gráfok" />
            <TabButton active={activeTab === 'heatmap'} onClick={() => setActiveTab('heatmap')} icon={<Map size={18}/>} label="3D Heatmap" />
            <TabButton active={activeTab === 'audio'} onClick={() => setActiveTab('audio')} icon={<Mic size={18}/>} label="Audio & Transcript" />
          </div>

          {/* TARTALOM MEGJELENÍTŐ */}
          <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
            {!sessionData ? (
              <div className="text-gray-500 flex justify-center items-center h-full">Töltés...</div>
            ) : (
              <>
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

                {/* 2. HEATMAP FÜL */}
                {activeTab === 'heatmap' && (
                  <div className="w-full h-full min-h-[600px] bg-black/40 rounded-xl border border-white/10 overflow-hidden shadow-lg">
                    {sessionData.heatmap_url ? (
                      <iframe src={sessionData.heatmap_url} className="w-full h-full border-none" title="3D Heatmap" />
                    ) : (
                      <p className="text-gray-500 p-6">Nincs 3D Heatmap ehhez a méréshez.</p>
                    )}
                  </div>
                )}

                {/* 3. AUDIO FÜL */}
                {activeTab === 'audio' && (
                  <div className="flex flex-col gap-6">
                    <div className="glass-panel p-6">
                      <h3 className="text-lg font-medium mb-4 text-gray-200">Whisper AI Leirat</h3>
                      <div className="bg-black/40 rounded-xl p-5 h-64 overflow-y-auto font-mono text-sm text-gray-300 border border-white/5 whitespace-pre-wrap shadow-inner leading-relaxed">
                        {sessionData.transcript}
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="glass-panel p-6 flex flex-col justify-center">
                        <h4 className="text-sm text-gray-400 mb-3 uppercase tracking-wider flex items-center gap-2">
                            <Mic size={16} /> Mikrofon
                        </h4>
                        {sessionData.mic_url ? <audio src={sessionData.mic_url} className="w-full rounded-lg outline-none" controls /> : <p className="text-gray-600">Nincs fájl.</p>}
                      </div>
                      <div className="glass-panel p-6 flex flex-col justify-center">
                        <h4 className="text-sm text-gray-400 mb-3 uppercase tracking-wider flex items-center gap-2">
                             <Play size={16} /> Játék Hang
                        </h4>
                        {sessionData.game_url ? <audio src={sessionData.game_url} className="w-full rounded-lg outline-none" controls /> : <p className="text-gray-600">Nincs fájl.</p>}
                      </div>
                    </div>
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
    <button onClick={onClick} className={`flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-all duration-300
      ${active ? 'bg-white/10 text-white shadow-[0_4px_12px_rgba(0,0,0,0.1)] border border-white/10' : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'}`}>
      {icon}<span>{label}</span>
    </button>
  );
}
export default App;