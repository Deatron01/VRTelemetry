import React, { useEffect, useRef } from 'react';
import {
  Upload, Play, Pause, Activity, Eye, Compass, Info, LayoutDashboard, Database,
  ShieldAlert, Download, FileText, FolderSearch, Video, LogOut, Users, Brain,
  Sun, Moon,
} from 'lucide-react';
import { useTelemetryStore } from '../../store/useTelemetryStore';
import { TelemetryParser } from '../../services/TelemetryParser';
import { useThemeStore } from '../../store/useThemeStore';

interface AppShellProps {
  children: React.ReactNode;
  currentRoute: string;
  onRouteChange: (r: string) => void;
  user?: { email: string; display_name: string };
  onLogout?: () => void;
}

/** Nav is grouped the way the work is: capture, then interpret, then inspect. */
const NAV_GROUPS: { label: string; items: { id: string; icon: React.ElementType; label: string }[] }[] = [
  {
    label: 'Session',
    items: [
      { id: 'overview', icon: LayoutDashboard, label: 'Overview' },
      { id: 'patients', icon: Users, label: 'Patients' },
      { id: 'record', icon: Video, label: 'Live Acquisition' },
      { id: 'explorer', icon: FolderSearch, label: 'Session Explorer' },
    ],
  },
  {
    label: 'Analysis',
    items: [
      { id: 'spatial', icon: Compass, label: 'Spatial Analysis' },
      { id: 'eye', icon: Eye, label: 'Eye Tracking' },
      { id: 'physiology', icon: Activity, label: 'Physiology' },
      { id: 'insights', icon: Brain, label: 'Research Insights' },
    ],
  },
  {
    label: 'Engineering',
    items: [
      { id: 'quality', icon: ShieldAlert, label: 'Data Quality' },
      { id: 'metadata', icon: FileText, label: 'Session Metadata' },
      { id: 'raw', icon: Database, label: 'Raw Telemetry' },
      { id: 'export', icon: Download, label: 'Export / Reports' },
    ],
  },
];

const SPEEDS: { value: number; label: string }[] = [
  { value: 0.25, label: '0.25\u00d7' },
  { value: 0.5, label: '0.5\u00d7' },
  { value: 1.0, label: '1.0\u00d7' },
  { value: 2.0, label: '2.0\u00d7' },
  { value: 5.0, label: '5.0\u00d7' },
];

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '—';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export const AppShell: React.FC<AppShellProps> = ({ children, currentRoute, onRouteChange, user, onLogout }) => {
  const {
    frames, metadata, currentFrameIdx, isPlaying, playbackSpeed,
    setFrameIdx, togglePlayback, setPlaybackSpeed, loadSession,
  } = useTelemetryStore();
  const { isDark, toggle: toggleTheme } = useThemeStore();
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
  };

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

  const hasSession = frames.length > 0;
  const elapsedSec = hasSession
    ? (frames[currentFrameIdx].timestamp_ns - frames[0].timestamp_ns) / 1e9
    : 0;
  const totalSec = hasSession
    ? (frames[frames.length - 1].timestamp_ns - frames[0].timestamp_ns) / 1e9
    : 0;
  const scrubPct = hasSession && frames.length > 1
    ? (currentFrameIdx / (frames.length - 1)) * 100
    : 0;

  const displayName = user?.display_name || user?.email || '';

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* ------------------------------------------------------------- rail --- */}
      <nav
        aria-label="Analysis Modules"
        className="glass-bare w-[236px] flex-none flex flex-col gap-3.5 overflow-y-auto px-3 py-3.5"
        style={{ borderRight: '1px solid var(--hair)' }}
      >
        <div className="flex items-center gap-2.5 px-2 pb-0.5 pt-1.5">
          <div className="clay-xs flex h-[34px] w-[34px] flex-none items-center justify-center" style={{ color: 'var(--s1)', borderRadius: 11 }}>
            <Activity className="h-[17px] w-[17px]" strokeWidth={2.1} />
          </div>
          <div className="leading-[1.15]">
            <div className="text-[14px] font-semibold tracking-[-0.01em]">VRTelemetry</div>
            <div className="text-[11px] text-ink-3">Research Studio</div>
          </div>
        </div>

        <div className="flex flex-col gap-[3px]">
          {NAV_GROUPS.map(group => (
            <React.Fragment key={group.label}>
              <div className="rail-section">{group.label}</div>
              {group.items.map(item => (
                <button
                  key={item.id}
                  onClick={() => onRouteChange(item.id)}
                  aria-current={currentRoute === item.id ? 'page' : undefined}
                  className="rail-btn"
                >
                  <item.icon className="h-[15px] w-[15px] flex-none" /> {item.label}
                </button>
              ))}
            </React.Fragment>
          ))}
        </div>

        {user && (
          <div className="clay-sm mt-auto flex items-center gap-2.5 px-2.5 py-2.5">
            <div
              className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-lg text-[11px] font-semibold"
              style={{ background: 'var(--s1-soft)', color: 'var(--s1)' }}
              aria-hidden="true"
            >
              {initialsOf(displayName)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12px] font-medium" title={displayName}>{displayName}</div>
              <div className="truncate text-[10px] text-ink-3" title={user.email}>{user.email}</div>
            </div>
            <button onClick={onLogout} aria-label="Sign out" title="Sign out" className="btn-ghost">
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </nav>

      {/* ---------------------------------------------------------- column --- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="glass-bare flex h-14 flex-none items-center gap-3 px-5"
          style={{ borderBottom: '1px solid var(--hair)', boxShadow: 'var(--glass-shadow)' }}
        >
          {metadata ? (
            <div className="clay-xs flex items-center gap-2 py-[5px] pl-2 pr-2.5">
              <span
                className="h-[7px] w-[7px] flex-none rounded-full"
                style={{ background: 'var(--s6)', boxShadow: '0 0 0 3px var(--s6-soft)' }}
                aria-hidden="true"
              />
              <span className="mono max-w-[280px] truncate text-[12px] font-medium">{metadata.filename}</span>
              {metadata.subject_id && (
                <span className="text-[11px] text-ink-3">· {metadata.subject_id}</span>
              )}
            </div>
          ) : (
            <div className="clay-xs flex items-center gap-2 py-[5px] pl-2 pr-2.5">
              <span
                className="h-[7px] w-[7px] flex-none rounded-full"
                style={{ background: 'var(--ink-3)' }}
                aria-hidden="true"
              />
              <span className="text-[12px] text-ink-3">No session loaded</span>
            </div>
          )}

          <div className="flex-1" />

          <input type="file" ref={fileInputRef} className="hidden" accept=".parquet" onChange={handleFileUpload} />

          <button
            onClick={toggleTheme}
            aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
            title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
            className="btn-clay"
          >
            {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            Theme
          </button>

          <button onClick={() => onRouteChange('export')} className="btn-clay">
            <Download className="h-3.5 w-3.5" />
            Export
          </button>

          <button onClick={() => fileInputRef.current?.click()} className="btn-accent">
            <Upload className="h-3.5 w-3.5" strokeWidth={2.2} />
            Load Parquet
          </button>
        </header>

        <main className="relative flex-1 overflow-y-auto px-6 pb-7 pt-5">
          {!hasSession && currentRoute !== 'explorer' && currentRoute !== 'record' && currentRoute !== 'patients' ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-8 text-center">
              <div className="clay mb-6 flex h-16 w-16 items-center justify-center" style={{ color: 'var(--s1)' }}>
                <Info className="h-8 w-8" />
              </div>
              <h2 className="mb-2 text-[22px] font-semibold tracking-[-0.02em]">Workspace Empty</h2>
              <p className="max-w-md text-[13px] text-ink-2">
                Import a <span className="mono">.parquet</span> telemetry session — or open one from Session Explorer — to begin multi-modal biometric analysis.
              </p>
              <button onClick={() => fileInputRef.current?.click()} className="btn-accent btn-accent-lg mt-6">
                <Upload className="h-4 w-4" strokeWidth={2.2} />
                Load Parquet
              </button>
            </div>
          ) : (
            children
          )}
        </main>

        {hasSession && (
          <footer
            className="glass-bare flex h-[60px] flex-none items-center gap-3.5 px-5"
            style={{ borderTop: '1px solid var(--hair)', boxShadow: 'var(--glass-shadow)' }}
          >
            <button
              onClick={togglePlayback}
              aria-label={isPlaying ? 'Pause playback' : 'Play back telemetry'}
              className="btn-icon btn-icon-lg"
            >
              {isPlaying
                ? <Pause className="h-[15px] w-[15px]" fill="currentColor" stroke="none" />
                : <Play className="h-[15px] w-[15px]" fill="currentColor" stroke="none" />}
            </button>

            <div className="seg seg-mono" role="group" aria-label="Playback speed">
              {SPEEDS.map(speed => (
                <button
                  key={speed.value}
                  onClick={() => setPlaybackSpeed(speed.value)}
                  aria-pressed={playbackSpeed === speed.value}
                  className={playbackSpeed === speed.value ? 'seg-item is-active' : 'seg-item'}
                >
                  {speed.label}
                </button>
              ))}
            </div>

            <label htmlFor="playback-scrub" className="sr-only">Scrub to frame</label>
            <input
              id="playback-scrub"
              type="range"
              className="scrub flex-1"
              style={{ ['--pct' as string]: `${scrubPct}%` }}
              min={0}
              max={frames.length - 1}
              value={currentFrameIdx}
              onChange={(e) => setFrameIdx(Number(e.target.value))}
            />

            <div className="mono tabular min-w-[168px] text-right text-[11.5px] text-ink-2">
              {elapsedSec.toFixed(2)}s / {totalSec.toFixed(2)}s{' '}
              <span className="text-ink-3">· f {currentFrameIdx.toLocaleString()}</span>
            </div>
          </footer>
        )}
      </div>
    </div>
  );
};
