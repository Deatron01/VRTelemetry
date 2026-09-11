import React, { useMemo } from 'react';
import { HeartPulse, Activity } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { useChartTokens } from '../services/chartTheme';
import { InfoTooltip } from '../components/InfoTooltip';

export const Physiology = () => {
  const { frames, metadata } = useTelemetryStore();
  const t = useChartTokens();

  // Downsample and align spatial kinematics with heart rate
  const chartData = useMemo(() => {
    if (!frames.length) return [];
    const maxPoints = 250;
    const step = Math.max(1, Math.floor(frames.length / maxPoints));

    return frames.filter((_, i) => i % step === 0).map((f, i, arr) => {
      let speed = 0;
      if (i > 0) {
        const prev = arr[i - 1];
        const dt = (f.timestamp_ns - prev.timestamp_ns) / 1e9;
        if (dt > 0) {
          const dx = f.hmd_pos_x - prev.hmd_pos_x;
          const dy = f.hmd_pos_y - prev.hmd_pos_y;
          const dz = f.hmd_pos_z - prev.hmd_pos_z;
          speed = Math.sqrt(dx * dx + dy * dy + dz * dz) / dt;
        }
      }
      return {
        time: (f.timestamp_ns / 1e9).toFixed(1),
        heartRate: f.heart_rate_bpm > 0 ? f.heart_rate_bpm : null,
        headSpeed: speed > 5 ? 0 : speed, // Cap extreme physics jitter for chart clarity
      };
    });
  }, [frames]);

  const hrSamples = chartData.filter(d => d.heartRate);
  const hrAvg = hrSamples.length
    ? hrSamples.reduce((acc, curr) => acc + (curr.heartRate || 0), 0) / hrSamples.length
    : 0;
  const hrPeak = chartData.reduce((m, d) => Math.max(m, d.heartRate || 0), 0);
  const speedAvg = chartData.length
    ? chartData.reduce((acc, curr) => acc + (curr.headSpeed || 0), 0) / chartData.length
    : 0;
  const speedPeak = chartData.reduce((m, d) => Math.max(m, d.headSpeed || 0), 0);

  return (
    <div className="mx-auto flex h-full max-w-[1360px] flex-col gap-4">
      <div>
        <h1 className="page-title">Cross-Modal Physiology</h1>
        <p className="page-sub">
          Cardiovascular response set against physical movement intensity across the session.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        <SplitCard
          tone="tone-6"
          icon={HeartPulse}
          provenance="MEASURED"
          title="Cardiovascular Response"
          infoId="physiology.hr"
          left={{ label: 'Avg', value: hrSamples.length ? hrAvg.toFixed(1) : '—', unit: 'BPM' }}
          right={{ label: 'Peak', value: hrPeak > 0 ? hrPeak.toFixed(1) : '—', unit: 'BPM' }}
        />
        <SplitCard
          tone="tone-1"
          icon={Activity}
          provenance="DERIVED"
          title="Motion Intensity (Head Velocity)"
          infoId="physiology.head-velocity"
          left={{ label: 'Avg', value: speedAvg.toFixed(2), unit: 'm/s' }}
          right={{ label: 'Peak', value: speedPeak.toFixed(2), unit: 'm/s' }}
        />
      </div>

      <div className="clay flex min-h-0 flex-1 flex-col p-4">
        <div className="mb-3.5 flex items-start justify-between gap-4">
          <div>
            <h2 className="m-0 flex items-center gap-1 text-[14px] font-semibold">
              Movement vs. Cardiovascular Activity <InfoTooltip id="physiology.chart" />
            </h2>
            <p className="m-0 mt-1 text-[12px] text-ink-3">
              Dual-axis view: heart rate on the left axis, head velocity on the right.
            </p>
          </div>
          <span className="section-note flex-none">
            {(metadata?.duration_sec ?? 0).toFixed(1)}s · {(metadata?.avg_sampling_hz ?? 0).toFixed(0)} Hz
          </span>
        </div>

        <div className="well min-h-0 flex-1 p-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 6, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={t.grid} />
              <XAxis dataKey="time" minTickGap={30} tick={{ fontSize: 11, fill: t.axis }} axisLine={false} tickLine={false} />

              {/* Left Y Axis for Heart Rate */}
              <YAxis yAxisId="left" domain={['dataMin - 10', 'dataMax + 10']} tick={{ fontSize: 11, fill: t.s6 }} axisLine={false} tickLine={false} />

              {/* Right Y Axis for Head Speed */}
              <YAxis yAxisId="right" orientation="right" domain={[0, 'dataMax']} tick={{ fontSize: 11, fill: t.s1 }} axisLine={false} tickLine={false} />

              <Tooltip contentStyle={t.tooltip} labelStyle={t.tooltipLabel} />
              <Line yAxisId="left" type="monotone" dataKey="heartRate" name="Heart Rate (BPM)" stroke={t.s6} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line yAxisId="right" type="monotone" dataKey="headSpeed" name="Head Speed (m/s)" stroke={t.s1} strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

const SplitCard: React.FC<{
  tone: string;
  icon: React.ElementType;
  provenance: string;
  title: string;
  infoId?: string;
  left: { label: string; value: string; unit: string };
  right: { label: string; value: string; unit: string };
}> = ({ tone, icon: Icon, provenance, title, infoId, left, right }) => (
  <div className={`clay p-3.5 ${tone}`}>
    <div className="text-tone mb-3 flex items-center gap-[7px]">
      <Icon className="h-3.5 w-3.5" />
      <span className="text-[11px] font-semibold tracking-[0.05em]">{provenance}</span>
      <span className="text-[12px] font-medium text-ink-2">{title}</span>
      {infoId && <InfoTooltip id={infoId} />}
    </div>
    <div className="well flex items-stretch p-3">
      {[left, right].map((cell, i) => (
        <div key={cell.label} className="flex-1 px-3" style={i === 1 ? { borderLeft: '1px solid var(--hair)' } : undefined}>
          <div className="stat-label mb-1.5">{cell.label}</div>
          <div className="stat-value">
            {cell.value}<span className="stat-unit">{cell.unit}</span>
          </div>
        </div>
      ))}
    </div>
  </div>
);
