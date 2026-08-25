import React, { useMemo } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { ShieldAlert, Activity, AlertTriangle, CheckCircle2 } from 'lucide-react';

export const DataQuality = () => {
  const { frames, metadata } = useTelemetryStore();

  const qualityStats = useMemo(() => {
    if (!frames.length || !metadata) return null;

    let hmdDropouts = 0;
    let eyeDropouts = 0;
    let maxJitterNs = 0;
    let totalJitterNs = 0;

    // Expected delta time between frames based on average sampling rate
    const expectedDtNs = (1 / metadata.avg_sampling_hz) * 1e9;

    for (let i = 1; i < frames.length; i++) {
      const prev = frames[i - 1];
      const curr = frames[i];
      
      // Calculate Jitter
      const dtNs = curr.timestamp_ns - prev.timestamp_ns;
      const jitter = Math.abs(dtNs - expectedDtNs);
      totalJitterNs += jitter;
      if (jitter > maxJitterNs) maxJitterNs = jitter;

      // Calculate Dropouts (transitioning from valid to invalid)
      if (prev.hmd_tracking_valid > 0 && curr.hmd_tracking_valid === 0) hmdDropouts++;
      if (prev.eye_tracking_valid > 0 && curr.eye_tracking_valid === 0) eyeDropouts++;
    }

    const avgJitterMs = (totalJitterNs / (frames.length - 1)) / 1e6;
    const maxJitterMs = maxJitterNs / 1e6;
    
    // Weighted quality score
    const hmdWeight = metadata.hmd_validity_pct * 0.4;
    const eyeWeight = metadata.eye_validity_pct * 0.4;
    const jitterWeight = Math.max(0, 20 - (avgJitterMs * 2)); // Penalize high jitter
    const totalScore = hmdWeight + eyeWeight + jitterWeight;

    const completeFrames = frames.filter(f => f.hmd_tracking_valid > 0 && f.eye_tracking_valid > 0).length;
    const dataCompletenessPct = (completeFrames / frames.length) * 100;

    return {
      hmdDropouts,
      eyeDropouts,
      avgJitterMs,
      maxJitterMs,
      totalScore,
      dataCompletenessPct,
    };
  }, [frames, metadata]);

  if (!qualityStats || !metadata) return null;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3 mb-6">
        <ShieldAlert className="w-8 h-8 text-research-graphite" />
        <div>
          <h1 className="text-2xl font-semibold text-research-graphite">Telemetry Quality Assurance</h1>
          <p className="text-sm text-research-muted">Signal integrity, sampling stability, and dropout analysis.</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="glass-panel p-6 flex flex-col items-center justify-center text-center">
          <div className="text-sm font-medium text-research-muted uppercase tracking-wide mb-2">Overall Quality Score</div>
          <div className={`text-5xl font-bold ${qualityStats.totalScore > 90 ? 'text-research-green' : 'text-research-blue'}`}>
            {qualityStats.totalScore.toFixed(1)}
          </div>
          <p className="text-xs text-research-muted mt-2">Weighted composite of validity and jitter</p>
        </div>
        
        <div className="glass-panel p-6">
          <div className="metric-label flex items-center gap-2"><Activity className="w-4 h-4"/> Sampling Stability</div>
          <div className="mt-4 space-y-3">
            <div className="flex justify-between items-center border-b border-research-border pb-2">
              <span className="text-sm text-research-graphite">Target Frequency</span>
              <span className="font-mono text-sm">{metadata.avg_sampling_hz.toFixed(1)} Hz</span>
            </div>
            <div className="flex justify-between items-center border-b border-research-border pb-2">
              <span className="text-sm text-research-graphite">Average Jitter</span>
              <span className="font-mono text-sm">{qualityStats.avgJitterMs.toFixed(2)} ms</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-research-graphite">Maximum Jitter</span>
              <span className="font-mono text-sm text-amber-500">{qualityStats.maxJitterMs.toFixed(2)} ms</span>
            </div>
          </div>
        </div>

        <div className="glass-panel p-6">
          <div className="metric-label flex items-center gap-2"><AlertTriangle className="w-4 h-4"/> Signal Dropouts</div>
          <div className="mt-4 space-y-3">
            <div className="flex justify-between items-center border-b border-research-border pb-2">
              <span className="text-sm text-research-graphite">HMD Tracking Losses</span>
              <span className="font-mono text-sm">{qualityStats.hmdDropouts} events</span>
            </div>
            <div className="flex justify-between items-center border-b border-research-border pb-2">
              <span className="text-sm text-research-graphite">Eye Tracking Losses</span>
              <span className="font-mono text-sm">{qualityStats.eyeDropouts} events</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-research-graphite">Data Completeness</span>
              <span className={`font-mono text-sm flex items-center gap-1 ${
                qualityStats.dataCompletenessPct > 90 ? 'text-research-green'
                : qualityStats.dataCompletenessPct > 70 ? 'text-amber-500'
                : 'text-red-500'
              }`}>
                <CheckCircle2 className="w-4 h-4" /> {qualityStats.dataCompletenessPct.toFixed(1)}%
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};