import { useMemo } from 'react';
import { Eye, Waves, Zap } from 'lucide-react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { useChartTokens } from '../services/chartTheme';

export const EyeTracking = () => {
  const frames = useTelemetryStore(state => state.frames);
  const t = useChartTokens();

  // Calculate Gaze Shift (Saccadic Activity) instead of Pupil size
  const chartData = useMemo(() => {
    if (!frames.length) return [];
    const maxPoints = 300;
    const step = Math.max(1, Math.floor(frames.length / maxPoints));

    return frames.filter((_, i) => i % step === 0).map((f, i, arr) => {
      let gazeShift = 0;

      // Calculate how much the eye rotation changed since the last sampled frame
      if (i > 0 && f.eye_tracking_valid > 0) {
        const prev = arr[i - 1];

        // Approximate angular velocity using quaternion delta magnitude
        const dx = f.left_eye_rot_x - prev.left_eye_rot_x;
        const dy = f.left_eye_rot_y - prev.left_eye_rot_y;
        const dz = f.left_eye_rot_z - prev.left_eye_rot_z;
        const dw = f.left_eye_rot_w - prev.left_eye_rot_w;

        // Scale it up purely for visual chart readability
        gazeShift = Math.sqrt(dx * dx + dy * dy + dz * dz + dw * dw) * 100;
      }

      return {
        time: (f.timestamp_ns / 1e9).toFixed(1),
        seconds: frames.length ? (f.timestamp_ns - frames[0].timestamp_ns) / 1e9 : 0,
        gazeActivity: f.eye_tracking_valid > 0 ? gazeShift : 0,
      };
    });
  }, [frames]);

  const validityPct = frames.length > 0
    ? (frames.filter(f => f.eye_tracking_valid > 0).length / frames.length) * 100
    : 0;

  const gazeMean = chartData.length
    ? chartData.reduce((acc, curr) => acc + curr.gazeActivity, 0) / chartData.length
    : 0;

  // Reported alongside the peak, because "how big" without "when" isn't
  // actionable — the researcher wants to scrub to that moment.
  const peak = chartData.reduce(
    (best, d) => (d.gazeActivity > best.gazeActivity ? d : best),
    { gazeActivity: 0, seconds: 0 },
  );

  return (
    <div className="mx-auto flex h-full max-w-[1360px] flex-col gap-4">
      <div>
        <h1 className="page-title">Eye Tracking Laboratory</h1>
        <p className="page-sub">
          Saccadic activity and gaze stability derived from binocular quaternion deltas.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-3">
        <div className="clay tone-6 p-3.5">
          <div className="text-tone mb-2.5 flex items-center gap-[7px]">
            <Eye className="h-3.5 w-3.5" />
            <span className="text-[11px] font-semibold tracking-[0.05em]">MEASURED</span>
          </div>
          <div className="mb-1.5 text-[12px] font-medium text-ink-2">Binocular Tracking Validity</div>
          <div className="stat-value stat-value-lg text-tone mb-2.5">
            {validityPct.toFixed(1)}<span className="stat-unit">%</span>
          </div>
          <div className="well well-sm p-[7px]">
            <div className="bar bar-sm">
              <div className="bar-fill" style={{ width: `${Math.min(100, validityPct)}%` }} />
            </div>
          </div>
        </div>

        <div className="clay tone-5 p-3.5">
          <div className="mb-2.5 flex items-center justify-between gap-2">
            <div className="text-tone flex items-center gap-[7px]">
              <Waves className="h-3.5 w-3.5" />
              <span className="text-[11px] font-semibold tracking-[0.05em]">DERIVED</span>
            </div>
            <span className="mono text-[10px] text-ink-3">quat Δ</span>
          </div>
          <div className="mb-1.5 text-[12px] font-medium text-ink-2">Gaze Activity Mean</div>
          <div className="stat-value stat-value-lg text-tone mb-2">{gazeMean.toFixed(2)}</div>
          <p className="m-0 text-[11px] text-ink-3">Relative angular velocity</p>
        </div>

        <div className="clay tone-4 p-3.5" style={{ borderLeft: '3px solid var(--s4)' }}>
          <div className="mb-2.5 flex items-center justify-between gap-2">
            <div className="text-tone flex items-center gap-[7px]">
              <Zap className="h-3.5 w-3.5" />
              <span className="text-[11px] font-semibold tracking-[0.05em]">DERIVED</span>
            </div>
            <span className="mono text-[10px] text-ink-3">peak</span>
          </div>
          <div className="mb-1.5 text-[12px] font-medium text-ink-2">Peak Saccade Intensity</div>
          <div className="stat-value stat-value-lg text-tone mb-2">{peak.gazeActivity.toFixed(2)}</div>
          <p className="m-0 text-[11px] text-ink-3">
            Highest recorded gaze shift · <span className="mono">t {peak.seconds.toFixed(1)}s</span>
          </p>
        </div>
      </div>

      <div className="clay flex min-h-0 flex-1 flex-col p-4">
        <div className="mb-3.5 flex items-start justify-between gap-4">
          <div>
            <h2 className="m-0 text-[14px] font-semibold">Saccadic Activity &amp; Gaze Stability</h2>
            <p className="m-0 mt-1 text-[12px] text-ink-3">
              Spikes indicate rapid eye movement (saccades). Flat lines indicate fixation.
            </p>
          </div>
          <span className="chip tone-5 flex-none">DERIVED (QUATERNION Δ)</span>
        </div>

        <div className="well min-h-0 flex-1 p-2">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="colorActivity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={t.s5} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={t.s5} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={t.grid} />
              <XAxis dataKey="time" minTickGap={30} tick={{ fontSize: 11, fill: t.axis }} axisLine={false} tickLine={false} />
              <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11, fill: t.axis }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={t.tooltip}
                labelStyle={t.tooltipLabel}
                formatter={(value: number) => [value.toFixed(2), 'Activity Intensity']}
              />
              <Area
                type="monotone"
                dataKey="gazeActivity"
                name="Activity Intensity"
                stroke={t.s5}
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#colorActivity)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};
