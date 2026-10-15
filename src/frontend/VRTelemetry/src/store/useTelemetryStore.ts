import { create } from 'zustand';
import type { TelemetryFrame, SessionMetadata, DerivedMetrics } from '../types/telemetry';

interface TelemetryState {
  // Data State
  frames: TelemetryFrame[];
  metadata: SessionMetadata | null;
  metrics: DerivedMetrics | null;
  // Aliases for backward compatibility with Export component
  sessionMetadata: SessionMetadata | null; // alias for metadata
  sessionMetrics: DerivedMetrics | null;   // alias for metrics
  isLoading: boolean;

  // Playback State
  currentFrameIdx: number;
  isPlaying: boolean;
  playbackSpeed: number;
  timeRange: [number, number]; // Selection window [startIdx, endIdx]

  // Actions
  loadSession: (frames: TelemetryFrame[], metadata: SessionMetadata, metrics: DerivedMetrics) => void;
  setFrameIdx: (idx: number) => void;
  togglePlayback: () => void;
  setPlaybackSpeed: (speed: number) => void;
  setTimeRange: (range: [number, number]) => void;
}

export const useTelemetryStore = create<TelemetryState>((set) => ({
  frames: [],
  metadata: null,
  metrics: null,
  // Aliases for Export component compatibility
  sessionMetadata: null,
  sessionMetrics: null,
  isLoading: false,

  currentFrameIdx: 0,
  isPlaying: false,
  playbackSpeed: 1.0,
  timeRange: [0, 0],

  loadSession: (frames, metadata, metrics) => set({
    frames,
    metadata,
    metrics,
    // set aliases
    sessionMetadata: metadata,
    sessionMetrics: metrics,
    currentFrameIdx: 0,
    timeRange: [0, frames.length - 1]
  }),
  setFrameIdx: (idx) => set({ currentFrameIdx: idx }),
  togglePlayback: () => set((state) => ({ isPlaying: !state.isPlaying })),
  setPlaybackSpeed: (speed) => set({ playbackSpeed: speed }),
  setTimeRange: (range) => set({ timeRange: range })
}));
