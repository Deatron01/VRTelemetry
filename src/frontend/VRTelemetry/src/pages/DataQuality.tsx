import React, { useMemo } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Gauge } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { bucketRateHz, bucketDrops, bucketValidity, validityPct, toPolyline, toBars } from '../services/Series';

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

  // Per-channel validity: only channels this session actually carries, so an
  // absent sensor reads as absent rather than as 0% — very different diagnoses.
  const channels = useMemo(() => {
    const rows: { label: string; pct: number }[] = [];
    const push = (label: string, pct: number | null) => { if (pct !== null) rows.push({ label, pct }); };
    push('HMD pose', validityPct(frames, f => f.hmd_tracking_valid));
    push('Left controller pose', validityPct(frames, f => f.left_tracking_valid));
    push('Right controller pose', validityPct(frames, f => f.right_tracking_valid));
    push('Binocular gaze', validityPct(frames, f => f.eye_tracking_valid));
    push('Pupillometry', validityPct(frames, f => (f.left_pupil_size > 0 || f.right_pupil_size > 0 ? 1 : 0)));
    push('Heart rate', validityPct(frames, f => (f.heart_rate_bpm > 0 ? 1 : 0)));
    return rows;
  }, [frames]);

  const rateSeries = useMemo(() => bucketRateHz(frames, 30), [frames]);
  const dropSeries = useMemo(() => bucketDrops(frames, 40), [frames]);
  const gazeValidity = useMemo(() => bucketValidity(frames, f => f.eye_tracking_valid, 40), [frames]);

  if (!qualityStats || !metadata) return null;

  const scoreTone = qualityStats.totalScore > 90 ? 'tone-6' : qualityStats.totalScore > 75 ? 'tone-1' : 'tone-4';
  const completenessTone = qualityStats.dataCompletenessPct > 90 ? 'tone-6'
    : qualityStats.dataCompletenessPct > 70 ? 'tone-4' : 'tone-2';

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col gap-4">
      <div>
        <h1 className="page-title">Telemetry Quality Assurance</h1>
        <p className="page-sub">Signal integrity, sampling stability, and dropout analysis.</p>
      </div>

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-[0.85fr_1fr_1fr]">

        <div className={`clay flex flex-col items-center justify-center p-4 text-center ${scoreTone}`}>
          <div className="stat-label mb-3">Overall quality score</div>
          <div className="flex items-center gap-3">
            <div className="icon-tile"><Gauge className="h-[15px] w-[15px]" /></div>
            <div className="flex items-baseline gap-1.5">
              <span className="mono text-tone text-[42px] font-semibold leading-none tracking-[-0.03em]">
                {qualityStats.totalScore.toFixed(1)}
              </span>
              <span className="text-[12px] text-ink-3">of 100</span>
            </div>
          </div>
          <p className="m-0 mt-3 text-[11.5px] text-ink-3">Weighted composite of validity and jitter</p>
        </div>

        <div className="clay tone-1 p-4">
          <div className="text-tone mb-3 flex items-center gap-[7px]">
            <Activity className="h-3.5 w-3.5" />
            <span className="text-[12px] font-semibold">Sampling stability</span>
          </div>
          <div className="well mb-3 flex flex-col gap-2.5 p-3">
            <Row label="Target frequency" value={`${metadata.avg_sampling_hz.toFixed(1)} Hz`} />
            <Row label="Average jitter" value={`${qualityStats.avgJitterMs.toFixed(2)} ms`} />
            <Row label="Maximum jitter" value={`${qualityStats.maxJitterMs.toFixed(2)} ms`} tone="var(--s4)" />
          </div>
          <div className="well px-2 pb-1 pt-2">
            <svg viewBox="0 0 300 44" width="100%" height="44" preserveAspectRatio="none" role="img"
                 aria-label="Effective sampling rate across the session">
              {[11, 22, 33].map(y => (
                <line key={y} x1="0" y1={y} x2="300" y2={y} stroke="var(--well-grid)" strokeWidth="1" />
              ))}
              <polyline fill="none" stroke="var(--s1)" strokeWidth="1.8" strokeLinejoin="round"
                        points={toPolyline(rateSeries, 300, 44, { pad: 6 })} />
            </svg>
          </div>
        </div>

        <div className="clay tone-4 p-4" style={{ borderLeft: '3px solid var(--s4)' }}>
          <div className="text-tone mb-3 flex items-center gap-[7px]">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span className="text-[12px] font-semibold">Signal dropouts</span>
          </div>
          <div className="well mb-3 flex flex-col gap-2.5 p-3">
            <Row label="HMD tracking losses" value={`${qualityStats.hmdDropouts} events`} />
            <Row label="Eye tracking losses" value={`${qualityStats.eyeDropouts} events`} />
            <div className="flex items-center justify-between gap-3 text-[12px]">
              <span className="text-ink-3">Data completeness</span>
              <span className={`mono flex items-center gap-1.5 text-tone ${completenessTone}`}>
                <CheckCircle2 className="h-3.5 w-3.5" /> {qualityStats.dataCompletenessPct.toFixed(1)}%
              </span>
            </div>
          </div>
          <div className="well px-2 pb-1 pt-2">
            <svg viewBox="0 0 300 44" width="100%" height="44" preserveAspectRatio="none" role="img"
                 aria-label="Dropped frames and gaze-validity dips across the session">
              <line x1="0" y1="34" x2="300" y2="34" stroke="var(--well-grid)" strokeWidth="1" />
              <polyline fill="none" stroke="var(--s3)" strokeWidth="1.4" strokeLinejoin="round"
                        points={toPolyline(gazeValidity, 300, 44, { pad: 6, min: 0, max: 1 })} />
              {toBars(dropSeries, 300, 44, { barWidth: 4, baseline: 34 }).map((b, i) => (
                <rect key={i} x={b.x} y={b.y} width={b.width} height={b.height} fill="var(--s4)" />
              ))}
            </svg>
          </div>
        </div>
      </div>

      <div className="clay p-4">
        <div className="section-head">
          <h2 className="section-title">Per-channel validity</h2>
          <div className="section-rule" />
          <span className="section-note">{channels.length} channels present</span>
        </div>
        <div className="well grid grid-cols-1 gap-3.5 p-3.5 md:grid-cols-2 xl:grid-cols-3">
          {channels.map(c => (
            <div key={c.label} className={c.pct > 95 ? 'tone-6' : c.pct > 85 ? 'tone-3' : 'tone-4'}>
              <div className="bar-row">
                <span>{c.label}</span>
                <span className="mono">{c.pct.toFixed(1)}%</span>
              </div>
              <div className="bar">
                <div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, c.pct))}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const Row: React.FC<{ label: string; value: string; tone?: string }> = ({ label, value, tone }) => (
  <div className="flex items-center justify-between gap-3 text-[12px]">
    <span className="text-ink-3">{label}</span>
    <span className="mono" style={tone ? { color: tone } : undefined}>{value}</span>
  </div>
);
