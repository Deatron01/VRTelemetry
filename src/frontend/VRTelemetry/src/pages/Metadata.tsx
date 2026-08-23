import React from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { FileText, Cpu, Database, Activity } from 'lucide-react';

export const Metadata = () => {
  const { metadata, frames } = useTelemetryStore();

  if (!metadata || frames.length === 0) return null;

  // Extract actual schema columns from the first frame's keys
  const schemaColumns = Object.keys(frames[0]);

  return (
    <div className="max-w-6xl mx-auto space-y-6 flex flex-col h-[calc(100vh-140px)]">
      <div className="flex items-center gap-3 mb-4">
        <FileText className="w-8 h-8 text-research-graphite" />
        <div>
          <h1 className="text-2xl font-semibold text-research-graphite">Session & Device Metadata</h1>
          <p className="text-sm text-research-muted">Hardware diagnostics, schema definitions, and file context.</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-6">
          <div className="glass-panel p-6">
            <h3 className="font-semibold text-research-graphite mb-4 flex items-center gap-2 border-b border-research-border pb-2">
              <Database className="w-4 h-4 text-research-blue" /> File Information
            </h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Filename</span>
                <span className="text-sm font-mono bg-slate-100 px-2 rounded border border-slate-200">{metadata.filename}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Total Frames</span>
                <span className="text-sm font-mono">{metadata.total_frames.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Session Duration</span>
                <span className="text-sm font-mono">{metadata.duration_sec.toFixed(2)} seconds</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Start Timestamp</span>
                <span className="text-sm font-mono">{frames[0].timestamp_ns} ns</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">End Timestamp</span>
                <span className="text-sm font-mono">{frames[frames.length - 1].timestamp_ns} ns</span>
              </div>
            </div>
          </div>

          <div className="glass-panel p-6">
            <h3 className="font-semibold text-research-graphite mb-4 flex items-center gap-2 border-b border-research-border pb-2">
              <Cpu className="w-4 h-4 text-research-green" /> Hardware Capabilities Detected
            </h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Sampling Frequency</span>
                <span className="text-sm font-mono">~{metadata.avg_sampling_hz.toFixed(1)} Hz</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Eye Tracking Sensor</span>
                <span className={`text-sm font-mono ${metadata.channels_detected.includes('left_eye_pos_x') ? 'text-research-green' : 'text-research-muted'}`}>
                  {metadata.channels_detected.includes('left_eye_pos_x') ? 'DETECTED' : 'NOT AVAILABLE'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Pupillometry Sensor</span>
                <span className={`text-sm font-mono ${metadata.channels_detected.includes('left_pupil_size') ? 'text-research-green' : 'text-research-muted'}`}>
                  {metadata.channels_detected.includes('left_pupil_size') ? 'DETECTED' : 'NOT AVAILABLE'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-research-muted">Cardiovascular Sensor</span>
                <span className={`text-sm font-mono ${metadata.channels_detected.includes('heart_rate_bpm') ? 'text-research-green' : 'text-research-muted'}`}>
                  {metadata.channels_detected.includes('heart_rate_bpm') ? 'DETECTED' : 'NOT AVAILABLE'}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="glass-panel p-6 flex flex-col h-full">
          <h3 className="font-semibold text-research-graphite mb-4 flex items-center gap-2 border-b border-research-border pb-2">
            <Activity className="w-4 h-4 text-purple-500" /> Parquet Schema Extractor
          </h3>
          <p className="text-xs text-research-muted mb-4">
            The following physical telemetry channels were successfully mapped into the processing layer from the source file.
          </p>
          <div className="flex-1 overflow-y-auto bg-slate-50/50 rounded border border-research-border p-2">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              {schemaColumns.map((col) => (
                <div key={col} className="text-[11px] font-mono text-slate-600 truncate py-1 border-b border-slate-100 last:border-0">
                  {col}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};