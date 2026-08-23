import React, { useMemo } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';

export const EyeTracking = () => {
  const frames = useTelemetryStore(state => state.frames);

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
        gazeShift = Math.sqrt(dx*dx + dy*dy + dz*dz + dw*dw) * 100; 
      }

      return {
        time: (f.timestamp_ns / 1e9).toFixed(1),
        gazeActivity: f.eye_tracking_valid > 0 ? gazeShift : 0,
      };
    });
  }, [frames]);

  return (
    <div className="max-w-6xl mx-auto space-y-6 flex flex-col h-[calc(100vh-140px)]">
      <h1 className="text-2xl font-semibold text-research-graphite">Eye Tracking Laboratory</h1>
      
      <div className="grid grid-cols-3 gap-4">
        <div className="glass-panel p-5">
          <div className="metric-label">Binocular Tracking Validity</div>
          <div className="metric-value mt-2 text-research-green">
            {frames.length > 0 
              ? ((frames.filter(f => f.eye_tracking_valid > 0).length / frames.length) * 100).toFixed(1)
              : 0}%
          </div>
        </div>
        <div className="glass-panel p-5">
          <div className="metric-label">Gaze Activity Mean</div>
          <div className="metric-value mt-2 text-purple-600">
            {(chartData.reduce((acc, curr) => acc + curr.gazeActivity, 0) / (chartData.length || 1)).toFixed(2)}
          </div>
          <p className="text-xs text-research-muted mt-1">Relative angular velocity</p>
        </div>
        <div className="glass-panel p-5">
          <div className="metric-label">Peak Saccade Intensity</div>
          <div className="metric-value mt-2 text-amber-500">
            {Math.max(...chartData.map(d => d.gazeActivity)).toFixed(2)}
          </div>
          <p className="text-xs text-research-muted mt-1">Highest recorded gaze shift</p>
        </div>
      </div>

      <div className="glass-panel p-6 flex-1 min-h-0 flex flex-col">
        <div className="flex justify-between items-center mb-4">
          <div>
            <h3 className="font-semibold text-research-graphite">Saccadic Activity & Gaze Stability</h3>
            <p className="text-xs text-research-muted mt-1">Spikes indicate rapid eye movement (saccades). Flat lines indicate fixation.</p>
          </div>
          <span className="text-xs font-mono bg-slate-100 px-2 py-1 rounded text-slate-500 border border-slate-200">DERIVED (QUATERNION $\Delta$)</span>
        </div>
        
        <div className="flex-1 min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="colorActivity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#a855f7" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#a855f7" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="time" minTickGap={30} tick={{ fontSize: 12, fill: '#64748b' }} axisLine={false} tickLine={false} />
              <YAxis domain={['auto', 'auto']} tick={{ fontSize: 12, fill: '#64748b' }} axisLine={false} tickLine={false} />
              <Tooltip 
                contentStyle={{ borderRadius: '8px', border: '1px solid rgba(0,0,0,0.1)', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }} 
                labelStyle={{ color: '#64748b', fontSize: '12px' }}
                formatter={(value: number) => [value.toFixed(2), "Activity Intensity"]}
              />
              <Area 
                type="monotone" 
                dataKey="gazeActivity" 
                name="Activity Intensity" 
                stroke="#a855f7" 
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