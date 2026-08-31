import React from 'react';
import {
  Activity, Zap, ShieldCheck, AlertTriangle, Crosshair, Waves, Brain,
  HeartPulse, Microscope, ClipboardList, Info,
} from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import {
  bucketRateHz, bucketDrops, bucketSpeed, bucketMean, intervalStats,
  validityPct, toPolyline, toBars,
} from '../services/Series';
import type { TelemetryFrame } from '../types/telemetry';

interface OverviewProps {
  onNavigate?: (route: string) => void;
}

/** Provenance of a figure — the distinction the whole page is organised around. */
type Provenance = 'DERIVED' | 'REPORTED' | 'MEASURED';

const TONE: Record<Provenance, string> = {
  DERIVED: 'tone-1',
  REPORTED: 'tone-5',
  MEASURED: 'tone-6',
};

/** Magnitude of the quaternion delta between consecutive gaze samples. */
function gazeDelta(f: TelemetryFrame, prev: TelemetryFrame): number | null {
  if (!f.eye_tracking_valid || !prev.eye_tracking_valid) return null;
  const d = Math.hypot(
    f.left_eye_rot_x - prev.left_eye_rot_x,
    f.left_eye_rot_y - prev.left_eye_rot_y,
    f.left_eye_rot_z - prev.left_eye_rot_z,
    f.left_eye_rot_w - prev.left_eye_rot_w,
  );
  return Number.isFinite(d) ? d : null;
}

export const Overview: React.FC<OverviewProps> = ({ onNavigate }) => {
  const { frames, metadata, metrics } = useTelemetryStore();
  if (!metadata || !metrics) return null;

  // ---- Acquisition integrity ------------------------------------------------
  const stats = intervalStats(frames);
  const rateSeries = bucketRateHz(frames, 26);
  const dropSeries = bucketDrops(frames, 40);

  const totalDrops = metadata.total_dropped_frames ?? dropSeries.reduce((a, b) => a + b, 0);
  const totalFrames = metadata.total_frames || frames.length;
  const dropPct = totalFrames > 0 ? (totalDrops / (totalFrames + totalDrops)) * 100 : 0;

  // Contiguous runs of lossy buckets read as one incident, not N incidents.
  const clusters: number[] = [];
  dropSeries.forEach((d, i) => {
    if (d > 0 && (i === 0 || dropSeries[i - 1] === 0)) {
      clusters.push((i / dropSeries.length) * (metadata.duration_sec || 0));
    }
  });

  const controllerPct = validityPct(frames, (f) => {
    if (f.left_tracking_valid === undefined && f.right_tracking_valid === undefined) return undefined;
    return f.left_tracking_valid && f.right_tracking_valid ? 1 : 0;
  });

  const integrityRows: { label: string; pct: number; tone: string }[] = [
    { label: 'HMD pose', pct: metadata.hmd_validity_pct ?? 0, tone: 'tone-6' },
    { label: 'Binocular gaze', pct: metadata.eye_validity_pct ?? 0, tone: 'tone-3' },
    ...(controllerPct !== null ? [{ label: 'Controller pose', pct: controllerPct, tone: 'tone-5' }] : []),
  ];

  // ---- Analytic sparklines --------------------------------------------------
  const headSpeed = bucketSpeed(frames, { x: 'hmd_pos_x', y: 'hmd_pos_y', z: 'hmd_pos_z' }, 24);
  const saccade = bucketMean(frames, (f, i) => (i === 0 ? null : gazeDelta(f, frames[i - 1])), 24);
  const heartRate = bucketMean(frames, (f) => (f.heart_rate_bpm > 0 ? f.heart_rate_bpm : null), 22);

  const leftSpeed = bucketSpeed(frames, { x: 'left_pos_x' as const, y: 'left_pos_y' as const, z: 'left_pos_z' as const }, 1)[0];
  const rightSpeed = bucketSpeed(frames, { x: 'right_pos_x' as const, y: 'right_pos_y' as const, z: 'right_pos_z' as const }, 1)[0];
  const handMax = Math.max(leftSpeed ?? 0, rightSpeed ?? 0, 1e-6);

  const questionnaireMissing = Boolean(metadata.session_id) && !metadata.questionnaire_completed_at;

  const summary: { key: string; value: React.ReactNode; mono?: boolean }[] = [
    { key: 'Subject cohort', value: metadata.subject_id || 'Unknown subject', mono: true },
    { key: 'Apparatus', value: metadata.hmd_model || 'Generic HMD' },
    {
      key: 'Morphology (IPD)',
      value: metadata.subject_ipd_mm
        ? <>{metadata.subject_ipd_mm.toFixed(1)} <span className="text-[11px] text-ink-3">mm</span></>
        : 'Not recorded',
      mono: Boolean(metadata.subject_ipd_mm),
    },
    {
      key: 'Temporal window',
      value: <>{(metadata.duration_sec ?? 0).toFixed(1)} <span className="text-[11px] text-ink-3">s</span></>,
      mono: true,
    },
    {
      key: 'Acquisition matrix',
      value: <>{totalFrames.toLocaleString()} <span className="text-[11px] text-ink-3">frames</span></>,
      mono: true,
    },
  ];

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col gap-[18px]">

      <div className="flex items-end justify-between gap-6">
        <div>
          <h1 className="page-title">Diagnostic Overview</h1>
          <p className="page-sub">
            High-fidelity biophysical snapshot and experimental metadata for the active telemetry matrix.
          </p>
        </div>
      </div>

      {/* --- At-a-glance session identity ----------------------------------- */}
      <div className="summary-strip">
        {summary.map(cell => (
          <div key={cell.key} className="summary-cell">
            <div className="summary-key">{cell.key}</div>
            <div className={cell.mono ? 'summary-val mono truncate' : 'summary-val truncate'}>{cell.value}</div>
          </div>
        ))}
      </div>

      {questionnaireMissing && (
        <div className="notice tone-4">
          <div className="icon-tile">
            <ClipboardList className="h-[15px] w-[15px]" />
          </div>
          <p className="m-0 flex-1 text-[13px] text-ink-2">
            No post-session questionnaire has been recorded for this session — NASA-TLX and SSQ figures below are
            unavailable until it's completed.
          </p>
          {onNavigate && (
            <button onClick={() => onNavigate('explorer')} className="btn-clay text-tone font-semibold">
              Complete in Session Explorer
            </button>
          )}
        </div>
      )}

      {/* --- Acquisition integrity ------------------------------------------ */}
      <section>
        <div className="section-head">
          <h2 className="section-title">Acquisition integrity</h2>
          <div className="section-rule" />
          <span className="section-note">
            {(metadata.avg_sampling_hz ?? 0).toFixed(0)} Hz nominal · {totalFrames.toLocaleString()} frames
          </span>
        </div>

        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-3">

          {/* Sampling stability */}
          <div className="clay tone-1 p-3.5">
            <div className="mb-2.5 flex items-start justify-between gap-3">
              <div>
                <div className="stat-label mb-1">Sampling stability</div>
                <div className="stat-value">
                  {(metadata.avg_sampling_hz ?? 0).toFixed(1)}<span className="stat-unit">Hz</span>
                </div>
              </div>
              <div className="icon-tile"><Zap className="h-[15px] w-[15px]" /></div>
            </div>
            <div className="well px-2 pb-1 pt-2">
              <svg viewBox="0 0 300 56" width="100%" height="56" preserveAspectRatio="none" role="img"
                   aria-label={`Sampling frequency across the session, averaging ${(metadata.avg_sampling_hz ?? 0).toFixed(1)} hertz`}>
                {[14, 28, 42].map(y => (
                  <line key={y} x1="0" y1={y} x2="300" y2={y} stroke="var(--well-grid)" strokeWidth="1" />
                ))}
                <polyline fill="none" stroke="var(--s1)" strokeWidth="1.8" strokeLinejoin="round"
                          points={toPolyline(rateSeries, 300, 56, { pad: 8 })} />
              </svg>
            </div>
            <div className="stat-foot">
              <span>σ {stats ? stats.sigmaHz.toFixed(2) : '—'} Hz</span>
              <span>jitter {stats ? stats.jitterMs.toFixed(2) : '—'} ms</span>
              <span>max {stats ? stats.maxIntervalMs.toFixed(2) : '—'} ms</span>
            </div>
          </div>

          {/* Positional integrity */}
          <div className="clay tone-6 p-3.5">
            <div className="mb-2.5 flex items-start justify-between gap-3">
              <div>
                <div className="stat-label mb-1">Positional integrity</div>
                <div className="stat-value">
                  {(metadata.hmd_validity_pct ?? 0).toFixed(1)}<span className="stat-unit">%</span>
                </div>
              </div>
              <div className="icon-tile"><ShieldCheck className="h-[15px] w-[15px]" /></div>
            </div>
            <div className="well p-2.5">
              <div className="flex flex-col gap-2.5">
                {integrityRows.map(row => (
                  <div key={row.label} className={row.tone}>
                    <div className="bar-row">
                      <span>{row.label}</span>
                      <span className="mono">{row.pct.toFixed(1)}%</span>
                    </div>
                    <div className="bar">
                      <div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, row.pct))}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Signal attrition */}
          <div className="clay tone-4 p-3.5" style={{ borderLeft: '3px solid var(--s4)' }}>
            <div className="mb-2.5 flex items-start justify-between gap-3">
              <div>
                <div className="stat-label mb-1">Signal attrition</div>
                <div className="stat-value text-tone">
                  {totalDrops.toLocaleString()}<span className="stat-unit">drops</span>
                </div>
              </div>
              <div className="icon-tile"><AlertTriangle className="h-[15px] w-[15px]" /></div>
            </div>
            <div className="well px-2 pb-1 pt-2">
              <svg viewBox="0 0 300 56" width="100%" height="56" preserveAspectRatio="none" role="img"
                   aria-label={`Dropped frames across the session, ${totalDrops.toLocaleString()} in total`}>
                <line x1="0" y1="42" x2="300" y2="42" stroke="var(--well-grid)" strokeWidth="1" />
                {toBars(dropSeries, 300, 56, { barWidth: 4, baseline: 42 }).map((b, i) => (
                  <rect key={i} x={b.x} y={b.y} width={b.width} height={b.height} fill="var(--s4)" />
                ))}
              </svg>
            </div>
            <div className="stat-foot">
              <span>{dropPct.toFixed(2)}% of matrix</span>
              <span>{clusters.length} cluster{clusters.length === 1 ? '' : 's'}</span>
              <span>
                {clusters.length > 0
                  ? `t≈${clusters.slice(0, 2).map(t => `${t.toFixed(0)}s`).join(', ')}`
                  : 'none'}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* --- Psychophysical & kinematic analytics ---------------------------- */}
      <section>
        <div className="section-head">
          <h2 className="section-title">Psychophysical &amp; kinematic analytics</h2>
          <div className="section-rule" />
          <div className="seg" role="presentation">
            <span className="chip tone-1">DERIVED</span>
            <span className="chip tone-5">REPORTED</span>
            <span className="chip tone-6">MEASURED</span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">

          <AnalyticCard
            provenance="DERIVED" icon={Crosshair} note="< 0.15 m/s"
            label="Oculomotor Fixation Index"
            value={metrics.focus_ratio?.toFixed(1) ?? '—'} unit="%"
          >
            <Meter pct={metrics.focus_ratio ?? 0} />
          </AnalyticCard>

          <AnalyticCard
            provenance="DERIVED" icon={Waves} note="quat Δ"
            label="Peak Saccadic Velocity"
            value={metrics.peak_saccade !== undefined ? metrics.peak_saccade.toFixed(2) : '—'}
          >
            <Spark points={toPolyline(saccade, 200, 22, { pad: 3 })} label="Saccadic velocity across the session" />
          </AnalyticCard>

          <AnalyticCard
            provenance="DERIVED" icon={Activity} note="cervical"
            label="Cervical Kinematic Mean"
            value={metrics.avg_head_speed?.toFixed(2) ?? '—'} unit="m/s"
          >
            <Spark points={toPolyline(headSpeed, 200, 22, { pad: 3 })} label="Head translational velocity across the session" />
          </AnalyticCard>

          <AnalyticCard
            provenance="DERIVED" icon={Activity} note="bimanual"
            label="Bimanual Activity Index"
            value={metrics.avg_hand_speed !== undefined ? metrics.avg_hand_speed.toFixed(2) : '—'} unit="m/s"
          >
            {leftSpeed === null && rightSpeed === null ? (
              <Awaiting text="No controller channels in this session" />
            ) : (
              <div className="well-sm well flex items-center gap-1.5 p-[7px]">
                <span className="w-2 text-[10px] text-ink-3">L</span>
                <div className="bar bar-sm flex-1 tone-1">
                  <div className="bar-fill" style={{ width: `${((leftSpeed ?? 0) / handMax) * 100}%` }} />
                </div>
                <span className="w-2 text-[10px] text-ink-3">R</span>
                <div className="bar bar-sm flex-1 tone-3">
                  <div className="bar-fill" style={{ width: `${((rightSpeed ?? 0) / handMax) * 100}%` }} />
                </div>
              </div>
            )}
          </AnalyticCard>

          <AnalyticCard
            provenance="REPORTED" icon={Brain} note="NASA-RTLX"
            label="Cognitive Workload (NASA-RTLX)"
            value={metadata.nasa_tlx_rtlx !== undefined ? metadata.nasa_tlx_rtlx.toFixed(0) : null}
            caption={metadata.nasa_tlx_band}
          >
            {metadata.nasa_tlx_rtlx === undefined
              ? <Awaiting text="Awaiting questionnaire" />
              : <Meter pct={metadata.nasa_tlx_rtlx} />}
          </AnalyticCard>

          <AnalyticCard
            provenance="REPORTED" icon={AlertTriangle} note="SSQ"
            label="Simulator Sickness (SSQ Total)"
            value={metadata.ssq_total_severity !== undefined ? metadata.ssq_total_severity.toFixed(1) : null}
            caption={metadata.ssq_severity_band}
          >
            {metadata.ssq_total_severity === undefined
              ? <Awaiting text="Awaiting questionnaire" />
              : <Meter pct={Math.min(100, metadata.ssq_total_severity)} />}
          </AnalyticCard>

          <AnalyticCard
            provenance="MEASURED" icon={HeartPulse} note="ext. sensor"
            label="Cardiovascular Baseline"
            value={metrics.hr_mean > 0 ? metrics.hr_mean.toFixed(1) : null} unit="BPM"
          >
            {metrics.hr_mean > 0
              ? <Spark points={toPolyline(heartRate, 200, 22, { pad: 3 })} label="Heart rate across the session" tone="var(--s6)" />
              : <Awaiting text="No heart-rate channel in this session" />}
          </AnalyticCard>

          <AnalyticCard
            provenance="MEASURED" icon={Microscope} note="binocular"
            label="Ocular Sensor Integrity"
            value={(metadata.eye_validity_pct ?? 0).toFixed(1)} unit="%"
          >
            <Meter pct={metadata.eye_validity_pct ?? 0} />
          </AnalyticCard>
        </div>
      </section>
    </div>
  );
};

/* -------------------------------------------------------------- pieces --- */

const AnalyticCard: React.FC<{
  provenance: Provenance;
  icon: React.ElementType;
  note: string;
  label: string;
  value: string | null;
  unit?: string;
  caption?: string;
  children: React.ReactNode;
}> = ({ provenance, icon: Icon, note, label, value, unit, caption, children }) => (
  <div className={`clay p-3.5 ${TONE[provenance]} ${value === null ? 'opacity-[.92]' : 'lift'}`}>
    <div className="mb-2.5 flex items-center justify-between gap-2">
      <div className="text-tone flex items-center gap-[7px]">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-[11px] font-semibold tracking-[0.05em]">{provenance}</span>
      </div>
      <span className="mono text-[10px] text-ink-3">{note}</span>
    </div>
    <div className="mb-1.5 min-h-[32px] text-[12px] font-medium text-ink-2">{label}</div>
    {value === null ? (
      <div className="stat-empty mb-2.5">Not reported</div>
    ) : (
      <div className="stat-value stat-value-lg mb-2.5">
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
        {caption && <span className="ml-2 text-[13px] font-normal text-ink-3">{caption}</span>}
      </div>
    )}
    {children}
  </div>
);

const Meter: React.FC<{ pct: number }> = ({ pct }) => (
  <div className="well well-sm p-[7px]">
    <div className="bar bar-sm">
      <div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  </div>
);

const Spark: React.FC<{ points: string; label: string; tone?: string }> = ({ points, label, tone }) => (
  <div className="well well-sm px-[7px] pb-[2px] pt-[5px]">
    <svg viewBox="0 0 200 22" width="100%" height="22" preserveAspectRatio="none" role="img" aria-label={label}>
      {points
        ? <polyline fill="none" stroke={tone ?? 'var(--tone, var(--s1))'} strokeWidth="1.6" points={points} />
        : <line x1="0" y1="11" x2="200" y2="11" stroke="var(--well-grid)" strokeWidth="1.5" />}
    </svg>
  </div>
);

const Awaiting: React.FC<{ text: string }> = ({ text }) => (
  <div className="well well-sm flex items-center gap-[7px] p-[7px]">
    <Info className="h-3 w-3 flex-none text-ink-3" />
    <span className="text-[10.5px] text-ink-3">{text}</span>
  </div>
);
