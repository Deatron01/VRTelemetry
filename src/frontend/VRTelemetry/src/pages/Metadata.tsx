import React from 'react';
import { Cpu, Database, Activity } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { InfoTooltip } from '../components/InfoTooltip';

export const Metadata = () => {
  const { metadata, frames } = useTelemetryStore();

  if (!metadata || frames.length === 0) return null;

  // Extract actual schema columns from the first frame's keys
  const schemaColumns = Object.keys(frames[0]);

  const sensors: { label: string; channel: string }[] = [
    { label: 'Eye tracking sensor', channel: 'left_eye_pos_x' },
    { label: 'Pupillometry sensor', channel: 'left_pupil_size' },
    { label: 'Cardiovascular sensor', channel: 'heart_rate_bpm' },
    { label: 'Controller tracking', channel: 'left_pos_x' },
  ];

  return (
    <div className="mx-auto flex h-full max-w-[1360px] flex-col gap-4">
      <div>
        <h1 className="page-title">Session &amp; Device Metadata</h1>
        <p className="page-sub">Hardware diagnostics, schema definitions, and file context.</p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3.5 lg:grid-cols-2">
        <div className="flex flex-col gap-3.5">

          <div className="clay p-4">
            <div className="section-head">
              <span style={{ color: 'var(--s1)' }}><Database className="h-4 w-4" /></span>
              <h2 className="section-title">File Information</h2>
              <div className="section-rule" />
            </div>
            <div className="well flex flex-col gap-2.5 p-3">
              <Row label="Filename" value={metadata.filename} mono truncate />
              <Row label="Total frames" value={metadata.total_frames.toLocaleString()} mono />
              <Row label="Session duration" value={`${metadata.duration_sec.toFixed(2)} seconds`} mono />
              <Row label="Start timestamp" value={`${frames[0].timestamp_ns} ns`} mono infoId="metadata.timestamp" />
              <Row label="End timestamp" value={`${frames[frames.length - 1].timestamp_ns} ns`} mono infoId="metadata.timestamp" />
            </div>
          </div>

          <div className="clay p-4">
            <div className="section-head">
              <span style={{ color: 'var(--s6)' }}><Cpu className="h-4 w-4" /></span>
              <h2 className="section-title">Hardware Capabilities Detected</h2>
              <InfoTooltip id="metadata.sensor-detection" />
              <div className="section-rule" />
            </div>
            <div className="well flex flex-col gap-2.5 p-3">
              <Row label="Sampling frequency" value={`~${metadata.avg_sampling_hz.toFixed(1)} Hz`} mono />
              {sensors.map(s => {
                const present = metadata.channels_detected.includes(s.channel);
                return (
                  <div key={s.channel} className="flex items-center justify-between gap-3 text-[12px]">
                    <span className="text-ink-3">{s.label}</span>
                    <span className="mono text-[11px]" style={{ color: present ? 'var(--s6)' : 'var(--ink-3)' }}>
                      {present ? 'DETECTED' : 'NOT AVAILABLE'}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="clay flex min-h-0 flex-col p-4">
          <div className="section-head">
            <span style={{ color: 'var(--s5)' }}><Activity className="h-4 w-4" /></span>
            <h2 className="section-title">Parquet Schema Extractor</h2>
            <div className="section-rule" />
            <span className="section-note">{schemaColumns.length} channels</span>
          </div>
          <p className="m-0 mb-3 text-[12px] text-ink-3">
            The following physical telemetry channels were successfully mapped into the processing layer from the
            source file.
          </p>
          <div className="well min-h-0 flex-1 overflow-y-auto p-2.5">
            <div className="grid grid-cols-1 gap-x-5 sm:grid-cols-2">
              {schemaColumns.map(col => (
                <div
                  key={col}
                  className="mono truncate py-1.5 text-[11px] text-ink-2"
                  style={{ borderBottom: '1px solid var(--well-line)' }}
                  title={col}
                >
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

const Row: React.FC<{ label: string; value: string; mono?: boolean; truncate?: boolean; infoId?: string }> =
  ({ label, value, mono, truncate, infoId }) => (
  <div className="flex items-center justify-between gap-3 text-[12px]">
    <span className="flex flex-none items-center gap-1 text-ink-3">
      {label}
      {infoId && <InfoTooltip id={infoId} />}
    </span>
    <span className={`${mono ? 'mono' : ''} ${truncate ? 'min-w-0 truncate' : ''} text-[11.5px]`} title={value}>{value}</span>
  </div>
);
