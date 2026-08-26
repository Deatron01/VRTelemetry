import React, { useEffect, useRef } from 'react';
import { Upload, Play, Pause, Activity, Eye, Compass, Info, LayoutDashboard, Database, ShieldAlert, Download, FileText, FolderSearch, Video, LogOut } from 'lucide-react';
import { useTelemetryStore } from '../../store/useTelemetryStore';
import { TelemetryParser } from '../../services/TelemetryParser';

interface AppShellProps {
  children: React.ReactNode;
  currentRoute: string;
  onRouteChange: (r: string) => void;
  user?: { email: string; display_name: string };
  onLogout?: () => void;
}

export const AppShell: React.FC<AppShellProps> = ({ children, currentRoute, onRouteChange, user, onLogout }) => {
  const { frames, currentFrameIdx, isPlaying, setFrameIdx, togglePlayback, setPlaybackSpeed, loadSession } = useTelemetryStore();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef<number>();
  const previousTimeRef = useRef<number>();

  const animate = (time: number) => {
    if (previousTimeRef.current != undefined) {
      const state = useTelemetryStore.getState();
      
      if (state.isPlaying && state.frames.length > 0) {
        // 1. Calculate real-world delta time since the last browser render (in milliseconds)
        const dtMs = time - previousTimeRef.current;
        
        // 2. Convert ms to nanoseconds (1ms = 1e6 ns) and apply the UI playback speed multiplier
        const dtNs = dtMs * 1e6 * state.playbackSpeed;
        
        const currentSimTimeNs = state.frames[state.currentFrameIdx].timestamp_ns;
        const targetSimTimeNs = currentSimTimeNs + dtNs;
        
        let nextIdx = state.currentFrameIdx;
        
        // 3. Fast-forward and skip frames until we reach the correct timestamp.
        // This drops the 2000Hz data down to a perfectly synced 60Hz visual render.
        while (nextIdx < state.frames.length - 1 && state.frames[nextIdx].timestamp_ns < targetSimTimeNs) {
          nextIdx++;
        }

        // Loop back to start if we hit the end
        if (nextIdx >= state.frames.length - 1) {
          state.togglePlayback();
          nextIdx = 0;
        }

        // Only update React state if the frame index actually changed to save performance
        if (nextIdx !== state.currentFrameIdx) {
          state.setFrameIdx(nextIdx);
        }
      }
    }
    
    previousTimeRef.current = time;
    requestRef.current = requestAnimationFrame(animate);
  }

  useEffect(() => {
    requestRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(requestRef.current!);
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const { frames, metadata, metrics } = await TelemetryParser.parseFile(file);
    loadSession(frames, metadata, metrics);
  };

  const navItems = [
    { id: 'overview', icon: LayoutDashboard, label: 'Overview' },
    { id: 'record', icon: Video, label: 'Live Acquisition' },
    { id: 'explorer', icon: FolderSearch, label: 'Session Explorer' },
    { id: 'spatial', icon: Compass, label: 'Spatial Analysis' },
    { id: 'eye', icon: Eye, label: 'Eye Tracking' },
    { id: 'physiology', icon: Activity, label: 'Physiology' },
    { id: 'quality', icon: ShieldAlert, label: 'Data Quality' },
    { id: 'metadata', icon: FileText, label: 'Session Metadata' },
    { id: 'raw', icon: Database, label: 'Raw Telemetry' },
    { id: 'export', icon: Download, label: 'Export / Reports' },
  ];

  return (
    <div className="flex flex-col h-screen w-full">
      <header className="h-14 flex items-center justify-between px-6 bg-white/50 backdrop-blur-md border-b border-research-border z-10">
        <div className="flex items-center gap-2 text-research-graphite font-semibold">
          <Activity className="w-5 h-5 text-research-blue" />
          VRTelemetry <span className="font-light text-research-muted ml-1">Research Studio</span>
        </div>
        <div className="flex gap-4 items-center">
          <input type="file" ref={fileInputRef} className="hidden" accept=".parquet" onChange={handleFileUpload} />
          <button className="glass-button bg-research-blue/10 text-research-blue border-research-blue/20" onClick={() => fileInputRef.current?.click()}>
            <Upload className="w-4 h-4" /> Load Parquet
          </button>
          {user && (
            <div className="flex items-center gap-3 pl-4 border-l border-research-border">
              <span className="text-xs text-research-muted truncate max-w-[160px]">{user.display_name || user.email}</span>
              <button
                className="glass-button py-1.5 px-3 bg-slate-50 text-research-graphite border-slate-200"
                onClick={onLogout}
                title="Sign out"
              >
                <LogOut className="w-3.5 h-3.5" /> Sign Out
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-64 border-r border-research-border bg-white/30 backdrop-blur-sm p-4 flex flex-col gap-2 z-10">
          <div className="text-xs font-semibold text-research-muted uppercase tracking-wider mb-2 px-2">Analysis Modules</div>
          {navItems.map(item => (
            <button
              key={item.id}
              onClick={() => onRouteChange(item.id)}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${currentRoute === item.id ? 'bg-research-blue text-white shadow-sm' : 'text-research-graphite hover:bg-white/50'}`}
            >
              <item.icon className="w-4 h-4" /> {item.label}
            </button>
          ))}
        </aside>

        <main className="flex-1 overflow-y-auto p-6 relative">
          {frames.length === 0 && currentRoute !== 'explorer' && currentRoute !== 'record' ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8 text-research-muted">
              <div className="w-16 h-16 rounded-2xl bg-white shadow-glass border border-research-border flex items-center justify-center mb-6">
                <Info className="w-8 h-8 text-research-blue/60" />
              </div>
              <h2 className="text-2xl font-semibold text-research-text mb-2">Workspace Empty</h2>
              <p className="max-w-md text-sm">Import a .parquet telemetry session to begin multi-modal biometric analysis.</p>
            </div>
          ) : children}
        </main>
      </div>

      {frames.length > 0 && (
        <footer className="h-16 border-t border-research-border bg-white/60 backdrop-blur-xl px-6 flex items-center gap-4 z-20">
          <button onClick={togglePlayback} className="p-2 rounded-full hover:bg-black/5 text-research-text transition-colors">
            {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
          </button>
          
          <select 
            className="text-xs bg-transparent border border-research-border rounded px-2 py-1 outline-none font-mono"
            onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
            defaultValue={1.0}
          >
            <option value="0.25">0.25x</option>
            <option value="0.5">0.5x</option>
            <option value="1.0">1.0x (Real-Time)</option>
            <option value="2.0">2.0x</option>
            <option value="5.0">5.0x</option>
          </select>

          <input 
            type="range" 
            className="flex-1 accent-research-blue cursor-pointer" 
            min={0} 
            max={frames.length - 1} 
            value={currentFrameIdx}
            onChange={(e) => setFrameIdx(Number(e.target.value))}
          />
          
          <div className="font-mono text-xs text-research-muted min-w-[150px] text-right">
            Time: {((frames[currentFrameIdx].timestamp_ns - frames[0].timestamp_ns) / 1e9).toFixed(2)}s / {((frames[frames.length - 1].timestamp_ns - frames[0].timestamp_ns) / 1e9).toFixed(2)}s
          </div>
        </footer>
      )}
    </div>
  );
};