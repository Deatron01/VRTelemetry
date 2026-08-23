import React from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { 
  Activity, Clock, Database, ShieldCheck, Zap, User, Cpu, 
  AlertTriangle, Box, ScanEye, Brain, Fingerprint, Microscope, 
  Waves, Crosshair, HeartPulse
} from 'lucide-react';

export const Overview = () => {
  const { metadata, metrics } = useTelemetryStore();
  if (!metadata || !metrics) return null;

  // Section 1: Spatial-Temporal Acquisition Parameters
  const temporalCards = [
    { label: "Temporal Window", value: `${metadata.duration_sec?.toFixed(1) || 0}s`, icon: Clock },
    { label: "Acquisition Matrix", value: metadata.total_frames?.toLocaleString() || 0, icon: Database },
    { label: "Sampling Frequency", value: `${metadata.avg_sampling_hz?.toFixed(1) || 0} Hz`, icon: Zap },
    { label: "Positional Integrity", value: `${metadata.hmd_validity_pct?.toFixed(1) || 100}%`, icon: ShieldCheck },
  ];

  // Section 2: Clinical & Apparatus Context
  const contextCards = [
    { label: "Subject Cohort ID", value: metadata.subject_id || "Unknown Subject", icon: Fingerprint },
    { label: "Acquisition Apparatus", value: metadata.hmd_model || "Generic HMD", icon: Cpu },
    { label: "Morphology (IPD)", value: metadata.subject_ipd_mm ? `${metadata.subject_ipd_mm} mm` : "Not Recorded", icon: ScanEye },
    { 
      label: "Signal Attrition", 
      value: metadata.total_dropped_frames?.toLocaleString() || "0 Drops", 
      icon: AlertTriangle,
      isWarning: (metadata.total_dropped_frames || 0) > 0 
    },
  ];

  // Section 3: Psychophysical & Kinematic Analytics
  const analytics = [
    { label: "Oculomotor Fixation Index", value: `${metrics.focus_ratio?.toFixed(1) || 0}%`, desc: "Algorithmic (< 0.15 m/s)", icon: Crosshair, type: "DERIVED", color: "blue" },
    { label: "Peak Saccadic Velocity", value: `${metrics.peak_saccade?.toFixed(2) || 'N/A'}`, desc: "Quaternion Magnitude Δ", icon: Waves, type: "DERIVED", color: "blue" },
    { label: "Cervical Kinematic Mean", value: `${metrics.avg_head_speed?.toFixed(2) || 0} m/s`, desc: "Translational Velocity", icon: Activity, type: "DERIVED", color: "blue" },
    { label: "Bimanual Activity Index", value: `${metrics.avg_hand_speed?.toFixed(2) || 'N/A'} m/s`, desc: "Upper-Limb Translation", icon: Activity, type: "DERIVED", color: "blue" },
    { label: "Cognitive Load (NASA-TLX)", value: `${metadata.nasa_tlx_mental || 'N/A'}`, desc: "Subjective Parameter", icon: Brain, type: "REPORTED", color: "purple" },
    { label: "Vestibular Disruption (SSQ)", value: `${metadata.ssq_nausea_score || 'N/A'}`, desc: "Subjective Parameter", icon: AlertTriangle, type: "REPORTED", color: "purple" },
    { label: "Cardiovascular Baseline", value: `${metrics.hr_mean?.toFixed(1) || 0} BPM`, desc: "External Sensor Array", icon: HeartPulse, type: "MEASURED", color: "green" },
    { label: "Ocular Sensor Integrity", value: `${metadata.eye_validity_pct?.toFixed(1) || 0}%`, desc: "Binocular Tracking Confidence", icon: Microscope, type: "MEASURED", color: "green" },
  ];

  const getTypeStyles = (color: string) => {
    switch(color) {
      case 'purple': return 'bg-purple-50 text-purple-700 border-purple-200';
      case 'green': return 'bg-green-50 text-green-700 border-green-200';
      default: return 'bg-blue-50 text-blue-700 border-blue-200';
    }
  };

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">
      
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold mb-1 text-research-graphite tracking-tight">Diagnostic Overview</h1>
        <p className="text-sm text-research-muted">High-fidelity biophysical snapshot and experimental metadata for the active telemetry matrix.</p>
      </div>
      
      {/* 1. Spatial-Temporal Parameters */}
      <div className="grid grid-cols-4 gap-4">
        {temporalCards.map((c, i) => (
          <div key={i} className="glass-panel p-5 flex items-start justify-between hover:shadow-sm transition-shadow">
            <div>
              <div className="metric-label mb-1.5">{c.label}</div>
              <div className="text-2xl font-semibold text-research-graphite">{c.value}</div>
            </div>
            <div className="p-2.5 bg-slate-50/80 rounded-xl border border-slate-100">
              <c.icon className="w-5 h-5 text-research-blue/80" />
            </div>
          </div>
        ))}
      </div>

      {/* 2. Clinical Context */}
      <div>
        <h2 className="text-xs font-bold text-research-muted uppercase tracking-widest mb-4 border-b border-research-border pb-2 flex items-center gap-2">
          <Box className="w-4 h-4" /> Experimental Context & Morphology
        </h2>
        <div className="grid grid-cols-4 gap-4">
          {contextCards.map((c, i) => (
            <div key={i} className={`glass-panel p-4 flex items-center gap-4 transition-all ${c.isWarning ? 'border-amber-300 bg-amber-50/40' : 'hover:bg-white/60'}`}>
              <div className={`p-3 rounded-xl shadow-sm border ${c.isWarning ? 'bg-amber-100 text-amber-600 border-amber-200' : 'bg-white text-slate-500 border-slate-100'}`}>
                <c.icon className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-research-muted uppercase tracking-wider mb-0.5">{c.label}</div>
                <div className={`text-sm font-medium truncate max-w-[150px] ${c.isWarning ? 'text-amber-700' : 'text-research-graphite'}`}>
                  {c.value}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 3. Psychophysical Analytics */}
      <div>
        <h2 className="text-xs font-bold text-research-muted uppercase tracking-widest mb-4 border-b border-research-border pb-2 flex items-center gap-2">
          <Activity className="w-4 h-4" /> Psychophysical & Kinematic Analytics
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
          {analytics.map((c, i) => (
            <div key={i} className="glass-panel p-5 relative overflow-hidden group hover:border-research-blue/30 transition-colors">
              <div className="absolute top-0 right-0 p-4 opacity-100 md:opacity-0 group-hover:opacity-100 transition-opacity">
                <span className={`text-[9px] font-bold tracking-wider px-2 py-1 rounded border shadow-sm ${getTypeStyles(c.color)}`}>
                  {c.type}
                </span>
              </div>
              <div className="text-xs font-semibold text-research-muted mb-2 uppercase tracking-wide pr-16">{c.label}</div>
              <div className="text-3xl font-bold text-research-text mb-3 tracking-tight">{c.value}</div>
              <div className="text-xs text-slate-500 flex items-center gap-1.5 font-medium bg-slate-50/50 inline-flex px-2 py-1 rounded-md border border-slate-100">
                <c.icon className="w-3.5 h-3.5"/>
                {c.desc}
              </div>
            </div>
          ))}
        </div>
      </div>
      
    </div>
  );
};