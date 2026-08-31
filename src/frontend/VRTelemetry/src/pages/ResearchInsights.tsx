// src/frontend/VRTelemetry/src/pages/ResearchInsights.tsx
//
// The four scientific-analysis domains requested for VRTelemetry: cognitive
// load / mental workload, vestibular function & cybersickness risk, motor
// function & kinematics, and anthropometric-normalized physical exertion.
// Computation lives in services/ScienceMetrics.ts; this page is presentation
// + interpretation only.

import React, { useMemo, useState } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import {
  computeCognitiveLoad, computePosturalStability, computeMotorKinematics, computeExertionProfile,
} from '../services/ScienceMetrics';
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import {
  Brain, Compass, Activity, Flame, Info, Ruler,
} from 'lucide-react';
import { useChartTokens } from '../services/chartTheme';

type Tab = 'cognitive' | 'vestibular' | 'motor' | 'exertion';

const TABS: { id: Tab; label: string; icon: any }[] = [
  { id: 'cognitive', label: 'Cognitive', icon: Brain },
  { id: 'vestibular', label: 'Vestibular', icon: Compass },
  { id: 'motor', label: 'Motor', icon: Activity },
  { id: 'exertion', label: 'Exertion', icon: Flame },
];

/** The plain-language read on each domain — the part a reviewer actually quotes. */
const InterpretationCard: React.FC<{ text: string }> = ({ text }) => (
  <div className="notice tone-1">
    <div className="icon-tile"><Info className="h-[15px] w-[15px]" /></div>
    <p className="m-0 flex-1 text-[13px] leading-relaxed text-ink-2">{text}</p>
  </div>
);

const StatCard: React.FC<{ label: string; value: string; sub?: string; tone?: string }> = ({ label, value, sub, tone }) => (
  <div className={`clay p-3.5 ${tone ?? ''}`}>
    <div className="stat-label mb-2 min-h-[26px]">{label}</div>
    <div className={`stat-value ${tone ? 'text-tone' : ''}`}>{value}</div>
    {sub && <p className="m-0 mt-2 text-[11px] text-ink-3">{sub}</p>}
  </div>
);

/** Chart panel: clay frame, recessed well, consistent header treatment. */
const ChartPanel: React.FC<{ title: string; note: string; height: number; accent?: string; children: React.ReactNode }> =
  ({ title, note, height, accent, children }) => (
  <div className="clay p-4" style={accent ? { borderLeft: `3px solid ${accent}` } : undefined}>
    <h3 className="m-0 text-[14px] font-semibold">{title}</h3>
    <p className="m-0 mb-3 mt-1 text-[12px] text-ink-3">{note}</p>
    <div className="well p-2" style={{ height }}>{children}</div>
  </div>
);

export const ResearchInsights = () => {
  const { frames, metadata } = useTelemetryStore();
  const [tab, setTab] = useState<Tab>('cognitive');
  const t = useChartTokens();

  const axisProps = { tick: { fontSize: 11, fill: t.axis }, axisLine: false, tickLine: false } as const;
  const tooltipStyle = { contentStyle: t.tooltip, labelStyle: t.tooltipLabel };

  const cognitiveLoad = useMemo(() => computeCognitiveLoad(frames, metadata?.nasa_tlx_mental), [frames, metadata?.nasa_tlx_mental]);
  const postural = useMemo(() => computePosturalStability(frames, metadata?.ssq_total_severity), [frames, metadata?.ssq_total_severity]);
  const motor = useMemo(() => computeMotorKinematics(frames, metadata), [frames, metadata]);
  const exertion = useMemo(() => computeExertionProfile(frames, metadata?.nasa_tlx_physical, metadata?.thermal_comfort), [frames, metadata]);

  if (!frames.length) return null;

  return (
    <div className="mx-auto flex h-full max-w-[1360px] flex-col gap-4">
      <div>
        <h1 className="page-title">Research Insights</h1>
        <p className="page-sub">
          Scientific derived measures — cognitive, vestibular, motor, and physiological analysis of this session.
        </p>
      </div>

      <div role="tablist" aria-label="Research Insights sections" className="seg self-start">
        {TABS.map(item => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={`flex items-center gap-2 ${tab === item.id ? 'seg-item is-active' : 'seg-item'}`}
          >
            <item.icon className="h-3.5 w-3.5" /> {item.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 space-y-3.5 overflow-y-auto pb-2">
        {tab === 'cognitive' && (
          <>
            <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
              <StatCard tone="tone-5" label="Mean TEPR (vs scene baseline)" value={`${cognitiveLoad.meanTepr.toFixed(1)}%`} sub="Task-Evoked Pupillary Response" />
              <StatCard tone="tone-5" label="Peak TEPR" value={`+${cognitiveLoad.peakTepr.toFixed(1)}%`} sub={`at ${cognitiveLoad.peakTime.toFixed(1)}s`} />
              <StatCard label="Baseline Pupil Diameter" value={cognitiveLoad.globalBaselinePupil ? cognitiveLoad.globalBaselinePupil.toFixed(2) : 'N/A'} sub="First 10s (or 20% of session)" />
            </div>
            <ChartPanel
              title="Cognitive Load Index Over Time"
              note="Per-scene-baselined pupil dilation — a proxy for task-evoked cognitive effort (see interpretation for the PLR-compensation caveat)."
              height={260}
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={cognitiveLoad.timeSeries} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorCLI" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={t.s5} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={t.s5} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={t.grid} />
                  <XAxis dataKey="time" {...axisProps} label={{ value: 'Time (s)', position: 'insideBottom', offset: -2, fontSize: 11, fill: t.axis }} />
                  <YAxis {...axisProps} />
                  <Tooltip {...tooltipStyle} formatter={(v: number) => [v.toFixed(1), 'Cognitive Load Index']} />
                  <Area type="monotone" dataKey="cognitiveLoadIndex" stroke={t.s5} strokeWidth={2} fill="url(#colorCLI)" isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartPanel>
            <InterpretationCard text={cognitiveLoad.interpretation} />
          </>
        )}

        {tab === 'vestibular' && (
          <>
            <div className="grid grid-cols-2 gap-3.5 xl:grid-cols-4">
              <StatCard label="Total Sway Path Length" value={`${postural.totalPathLengthM.toFixed(2)} m`} />
              <StatCard label="Mean Sway Velocity" value={`${postural.meanSwayVelocity.toFixed(3)} m/s`} />
              <StatCard label="95% Sway Ellipse Area" value={`${postural.swayEllipseAreaM2.toFixed(4)} m²`} sub="Prieto et al., 1996" />
              <StatCard label="Low-Freq (<0.5Hz) Energy" value={`${(postural.lowFrequencyEnergyRatio * 100).toFixed(0)}%`} sub="Rising = cybersickness marker" />
            </div>
            <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
              <ChartPanel title="Head Sway Velocity" note="Planar (X/Z) head displacement rate over time." height={210}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={postural.swayTrend} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={t.grid} />
                    <XAxis dataKey="time" {...axisProps} />
                    <YAxis {...axisProps} />
                    <Tooltip {...tooltipStyle} formatter={(v: number) => [v.toFixed(3), 'Sway Velocity (m/s)']} />
                    <Line type="monotone" dataKey="swayVelocity" stroke={t.s4} strokeWidth={2} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </ChartPanel>
              <ChartPanel
                title="Cybersickness Risk Trend"
                note={`Windowed sway intensity, normalized 0-100 ${postural.riskTrendSlope > 0.01 ? '(rising)' : '(stable/falling)'}.`}
                height={210}
                accent="var(--s4)"
              >
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={postural.riskTrend} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={t.grid} />
                    <XAxis dataKey="time" {...axisProps} />
                    <YAxis {...axisProps} domain={[0, 100]} />
                    <Tooltip {...tooltipStyle} formatter={(v: number) => [v, 'Relative Risk']} />
                    <Bar dataKey="risk" fill={t.s2} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </ChartPanel>
            </div>
            <InterpretationCard text={postural.interpretation} />
          </>
        )}

        {tab === 'motor' && (
          <>
            <div className="grid grid-cols-2 gap-3.5 xl:grid-cols-4">
              <StatCard label="Left Normalized Jerk" value={motor.left.normalizedJerk.toFixed(1)} sub="Lower = smoother" />
              <StatCard label="Right Normalized Jerk" value={motor.right.normalizedJerk.toFixed(1)} sub="Lower = smoother" />
              <StatCard label="Speed Symmetry" value={`${(motor.speedSymmetryIndex * 100).toFixed(1)}% asymmetry`} />
              <StatCard label="Reach Symmetry" value={`${(motor.reachSymmetryIndex * 100).toFixed(1)}% asymmetry`} />
            </div>
            <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
              <StatCard
                label="Left Peak Reach"
                value={`${motor.left.maxReachM.toFixed(2)} m`}
                sub={motor.left.reachPctOfArmLength !== null ? `${motor.left.reachPctOfArmLength.toFixed(0)}% of calibrated arm length` : 'Arm length not calibrated for this session'}
              />
              <StatCard
                label="Right Peak Reach"
                value={`${motor.right.maxReachM.toFixed(2)} m`}
                sub={motor.right.reachPctOfArmLength !== null ? `${motor.right.reachPctOfArmLength.toFixed(0)}% of calibrated arm length` : 'Arm length not calibrated for this session'}
              />
            </div>
            <ChartPanel title="Bimanual Controller Speed" note="Left vs. right controller translational speed over time." height={210}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={t.grid} />
                  <XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']} {...axisProps} allowDuplicatedCategory={false} />
                  <YAxis {...axisProps} />
                  <Tooltip {...tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line data={motor.left.timeSeries} type="monotone" dataKey="speed" name="Left Hand (m/s)" stroke={t.s1} strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line data={motor.right.timeSeries} type="monotone" dataKey="speed" name="Right Hand (m/s)" stroke={t.s6} strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartPanel>
            <InterpretationCard text={motor.interpretation} />
          </>
        )}

        {tab === 'exertion' && (
          <>
            <div className="summary-strip items-center gap-2">
              <Ruler className="ml-4 h-[18px] w-[18px] flex-none" style={{ color: 'var(--s1)' }} aria-hidden="true" />
              <div className="grid flex-1 grid-cols-2 md:grid-cols-4">
                <div className="summary-cell"><span className="summary-key">Height</span><span className="summary-val mono">{metadata?.height_cm ? `${metadata.height_cm} cm` : '—'}</span></div>
                <div className="summary-cell"><span className="summary-key">Weight</span><span className="summary-val mono">{metadata?.weight_kg ? `${metadata.weight_kg} kg` : '—'}</span></div>
                <div className="summary-cell"><span className="summary-key">IPD</span><span className="summary-val mono">{metadata?.subject_ipd_mm ? `${metadata.subject_ipd_mm.toFixed(1)} mm` : '—'}</span></div>
                <div className="summary-cell"><span className="summary-key">Dominant hand</span><span className="summary-val">{metadata?.dominant_hand || '—'}</span></div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3.5 xl:grid-cols-4">
              <StatCard label="Resting HR Estimate" value={exertion.restingHrEstimate ? `${exertion.restingHrEstimate.toFixed(0)} BPM` : 'N/A'} />
              <StatCard label="Peak HR" value={exertion.peakHr ? `${exertion.peakHr.toFixed(0)} BPM` : 'N/A'} />
              <StatCard label="Cardiovascular Drift" value={`${exertion.hrDriftBpm >= 0 ? '+' : ''}${exertion.hrDriftBpm.toFixed(1)} BPM`} sub={`${exertion.hrDriftRatePerMin >= 0 ? '+' : ''}${exertion.hrDriftRatePerMin.toFixed(2)} BPM/min`} />
              <StatCard label="Composite Exertion Index" value={`${exertion.exertionIndex.toFixed(0)}/100`} />
            </div>
            <ChartPanel title="Heart Rate vs. Movement Intensity" note="Cross-modal view of cardiovascular response and physical activity." height={210}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={exertion.timeSeries} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={t.grid} />
                  <XAxis dataKey="time" {...axisProps} />
                  <YAxis yAxisId="left" {...axisProps} tick={{ fontSize: 12, fill: t.s2 }} />
                  <YAxis yAxisId="right" orientation="right" {...axisProps} tick={{ fontSize: 12, fill: t.s4 }} />
                  <Tooltip {...tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line yAxisId="left" type="monotone" dataKey="hr" name="Heart Rate (BPM)" stroke={t.s2} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
                  <Line yAxisId="right" type="monotone" dataKey="kinematicIntensity" name="Movement Intensity" stroke={t.s4} strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartPanel>
            <InterpretationCard text={exertion.interpretation} />
          </>
        )}
      </div>
    </div>
  );
};
