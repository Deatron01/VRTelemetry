import React, { useMemo } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

export const Physiology = () => {
  const frames = useTelemetryStore(state => state.frames);

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
          speed = Math.sqrt(dx*dx + dy*dy + dz*dz) / dt;
        }
      }
      return {
        time: (f.timestamp_ns / 1e9).toFixed(1),
        heartRate: f.heart_rate_bpm > 0 ? f.heart_rate_bpm : null,
        headSpeed: speed > 5 ? 0 : speed, // Cap extreme physics jitter for chart clarity
      };
    });
  }, [frames]);

  return (
    <div className="max-w-6xl mx-auto space-y-6 flex flex-col h-[calc(100vh-140px)]">
      <h1 className="text-2xl font-semibold text-research-graphite">Cross-Modal Physiology</h1>
      
      <div className="grid grid-cols-2 gap-4">
        <div className="glass-panel p-5">
          <div className="metric-label">Cardiovascular Response</div>
          <p className="text-sm text-research-muted mt-1 mb-2">Measured heart rate telemetry.</p>
          <div className="flex gap-4 mt-2">
            <div>
              <span className="text-xs text-research-muted uppercase">Avg</span>
              <div className="text-xl font-semibold text-research-text">
                {Math.round(chartData.reduce((acc, curr) => acc + (curr.heartRate || 0), 0) / (chartData.filter(d => d.heartRate).length || 1))} BPM
              </div>
            </div>
            <div>
              <span className="text-xs text-research-muted uppercase">Peak</span>
              <div className="text-xl font-semibold text-research-text">
                {Math.round(Math.max(...chartData.map(d => d.heartRate || 0)))} BPM
              </div>
            </div>
          </div>
        </div>
        
        <div className="glass-panel p-5">
          <div className="metric-label">Motion Intensity (Head Velocity)</div>
          <p className="text-sm text-research-muted mt-1 mb-2">Derived spatial acceleration.</p>
          <div className="flex gap-4 mt-2">
            <div>
              <span className="text-xs text-research-muted uppercase">Avg</span>
              <div className="text-xl font-semibold text-research-text">
                {(chartData.reduce((acc, curr) => acc + (curr.headSpeed || 0), 0) / (chartData.length || 1)).toFixed(2)} m/s
              </div>
            </div>
            <div>
              <span className="text-xs text-research-muted uppercase">Peak</span>
              <div className="text-xl font-semibold text-research-text">
                {Math.max(...chartData.map(d => d.headSpeed || 0)).toFixed(2)} m/s
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="glass-panel p-6 flex-1 min-h-0 flex flex-col">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-research-graphite">Movement vs. Cardiovascular Activity</h3>
          <span className="text-xs font-mono bg-slate-100 px-2 py-1 rounded text-slate-500 border border-slate-200">CROSS-MODAL</span>
        </div>
        <div className="flex-1 min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="time" minTickGap={30} tick={{ fontSize: 12, fill: '#64748b' }} axisLine={false} tickLine={false} />
              
              {/* Left Y Axis for Heart Rate */}
              <YAxis yAxisId="left" domain={['dataMin - 10', 'dataMax + 10']} tick={{ fontSize: 12, fill: '#ef4444' }} axisLine={false} tickLine={false} />
              
              {/* Right Y Axis for Head Speed */}
              <YAxis yAxisId="right" orientation="right" domain={[0, 'dataMax']} tick={{ fontSize: 12, fill: '#f59e0b' }} axisLine={false} tickLine={false} />
              
              <Tooltip 
                contentStyle={{ borderRadius: '8px', border: '1px solid rgba(0,0,0,0.1)', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }} 
                labelStyle={{ color: '#64748b', fontSize: '12px' }}
              />
              <Line yAxisId="left" type="monotone" dataKey="heartRate" name="Heart Rate (BPM)" stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line yAxisId="right" type="monotone" dataKey="headSpeed" name="Head Speed (m/s)" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};