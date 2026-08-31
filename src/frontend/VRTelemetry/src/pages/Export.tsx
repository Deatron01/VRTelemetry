// src/frontend/VRTelemetry/src/pages/Export.tsx

import React, { useEffect, useState } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { Download, FileJson, FileSpreadsheet, FileText, Check, Upload, ShieldAlert, AlertCircle } from 'lucide-react';
import {
  computeCognitiveLoad, computePosturalStability, computeMotorKinematics, computeExertionProfile,
} from '../services/ScienceMetrics';

interface SyncPendingItem {
  session_id: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
}

interface SyncStatus {
  pending_count: number;
  pending_sessions: number;
  pending_patients: number;
  pending: SyncPendingItem[];
}

interface PatientRecord {
  patient_id: string;
  display_name: string;
  gdpr_consent_given: number;
  is_anonymized: number;
  [key: string]: any;
}

/** Wraps a CSV field in quotes and escapes embedded quotes/commas/newlines — the
 * previous export just joined raw values with commas, which corrupts the file
 * the moment any value contains one (e.g. a free-text health-conditions note). */
function csvField(value: unknown): string {
  if (value === null || value === undefined) return '';
  const str = String(value);
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

export const Export = () => {
  const { metadata, metrics, frames } = useTelemetryStore();
  const [isExporting, setIsExporting] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);

  const [purposeConsent, setPurposeConsent] = useState(false);
  const [includeHealthData, setIncludeHealthData] = useState(false);
  const [linkedPatient, setLinkedPatient] = useState<PatientRecord | null>(null);

  useEffect(() => {
    fetch('http://localhost:8000/api/sync/status')
      .then(r => r.json())
      .then(setSyncStatus)
      .catch(() => setSyncStatus(null));
  }, []);

  // Consent gating: if this session is linked to a patient, look up their current
  // consent state so export can be blocked the moment consent has been withdrawn
  // or the record erased — exporting is processing, same as recording is.
  useEffect(() => {
    if (!metadata?.patient_id) { setLinkedPatient(null); return; }
    fetch('http://localhost:8000/api/patients')
      .then(r => r.json())
      .then((patients: PatientRecord[]) => setLinkedPatient(patients.find(p => p.patient_id === metadata.patient_id) || null))
      .catch(() => setLinkedPatient(null));
  }, [metadata?.patient_id]);

  const patientConsentBlocked = Boolean(linkedPatient) && (linkedPatient!.is_anonymized === 1 || !linkedPatient!.gdpr_consent_given);
  const canExport = purposeConsent && !patientConsentBlocked;

  // Only meaningful for sessions backed by a real session_metadata row; a raw
  // drag-dropped .parquet has no questionnaire to be missing in the first place.
  const questionnaireMissing = Boolean(metadata?.session_id) && !metadata?.questionnaire_completed_at;

  const handleSyncNow = async () => {
    setIsSyncing(true);
    try {
      await fetch('http://localhost:8000/api/sync/retry', { method: 'POST' });
      const status = await fetch('http://localhost:8000/api/sync/status').then(r => r.json());
      setSyncStatus(status);
    } finally {
      setIsSyncing(false);
    }
  };

  const downloadBlob = (content: string, filename: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const scienceMetrics = () => ({
    cognitive_load: computeCognitiveLoad(frames, metadata?.nasa_tlx_mental),
    postural_stability: computePosturalStability(frames, metadata?.ssq_total_severity),
    motor_kinematics: computeMotorKinematics(frames, metadata),
    exertion_profile: computeExertionProfile(frames, metadata?.nasa_tlx_physical, metadata?.thermal_comfort),
  });

  const handleExportCSV = () => {
    if (!frames.length || !canExport) return;
    setIsExporting(true);
    setTimeout(() => {
      const columns = Object.keys(frames[0]);
      const headerRow = columns.map(csvField).join(',');
      const rows = frames.map(frame => columns.map(col => csvField((frame as any)[col])).join(',')).join('\r\n');
      downloadBlob(`${headerRow}\r\n${rows}`, `${metadata?.filename || 'session'}_raw_telemetry.csv`, 'text/csv');
      setIsExporting(false);
    }, 300);
  };

  const handleExportSummaryCSV = () => {
    if (!metadata || !canExport) return;
    setIsExporting(true);
    const sm = scienceMetrics();
    const summary: Record<string, unknown> = {
      ...metadata,
      derived_focus_ratio_pct: metrics?.focus_ratio,
      derived_avg_head_speed: metrics?.avg_head_speed,
      derived_mean_pupil_diameter: metrics?.mean_pupil_diameter,
      derived_hr_mean: metrics?.hr_mean,
      cognitive_load_mean_tepr_pct: sm.cognitive_load.meanTepr,
      postural_total_sway_path_m: sm.postural_stability.totalPathLengthM,
      postural_sway_ellipse_area_m2: sm.postural_stability.swayEllipseAreaM2,
      motor_left_normalized_jerk: sm.motor_kinematics.left.normalizedJerk,
      motor_right_normalized_jerk: sm.motor_kinematics.right.normalizedJerk,
      exertion_index: sm.exertion_profile.exertionIndex,
      exertion_hr_drift_bpm: sm.exertion_profile.hrDriftBpm,
    };
    if (includeHealthData && linkedPatient) {
      for (const [k, v] of Object.entries(linkedPatient)) summary[`patient_${k}`] = v;
    }
    const headers = Object.keys(summary).map(csvField).join(',');
    const values = Object.values(summary).map(csvField).join(',');
    downloadBlob(`${headers}\r\n${values}`, `${metadata.filename || 'session'}_summary.csv`, 'text/csv');
    setIsExporting(false);
  };

  const handleExportJSON = () => {
    if (!canExport) return;
    setIsExporting(true);
    const sm = scienceMetrics();
    const payload: Record<string, unknown> = {
      export_generated_at: new Date().toISOString(),
      session_metadata: metadata,
      derived_metrics: metrics,
      science_metrics: {
        cognitive_load: sm.cognitive_load,
        postural_stability: sm.postural_stability,
        motor_kinematics: sm.motor_kinematics,
        exertion_profile: sm.exertion_profile,
      },
      data_summary: { total_samples: frames.length, duration: metadata?.duration_sec },
    };
    if (includeHealthData) {
      payload.subjective_questionnaire = {
        nasa_tlx_mental: metadata?.nasa_tlx_mental,
        nasa_tlx_physical: metadata?.nasa_tlx_physical,
        nasa_tlx_temporal: metadata?.nasa_tlx_temporal,
        nasa_tlx_performance: metadata?.nasa_tlx_performance,
        nasa_tlx_effort: metadata?.nasa_tlx_effort,
        nasa_tlx_frustration: metadata?.nasa_tlx_frustration,
        nasa_tlx_rtlx: metadata?.nasa_tlx_rtlx,
        ssq_nausea_score: metadata?.ssq_nausea_score,
        ssq_oculomotor_score: metadata?.ssq_oculomotor_score,
        ssq_disorientation: metadata?.ssq_disorientation,
        ssq_total_severity: metadata?.ssq_total_severity,
        thermal_comfort: metadata?.thermal_comfort,
        session_rating: metadata?.session_rating,
      };
      if (linkedPatient) payload.patient_health_profile = linkedPatient;
    }
    downloadBlob(JSON.stringify(payload, null, 2), `${metadata?.filename || 'session'}_analysis.json`, 'application/json');
    setIsExporting(false);
  };

  const handleExportReport = () => {
    if (!canExport) return;
    const sm = scienceMetrics();
    const healthSection = includeHealthData ? `
          <h2>Subjective Questionnaire</h2>
          <ul>
            <li><strong>NASA-TLX (RTLX):</strong> ${metadata?.nasa_tlx_rtlx ?? 'Not reported'} ${metadata?.nasa_tlx_band ? `(${metadata.nasa_tlx_band})` : ''}</li>
            <li><strong>SSQ Total Severity:</strong> ${metadata?.ssq_total_severity ?? 'Not reported'} ${metadata?.ssq_severity_band ? `(${metadata.ssq_severity_band})` : ''}</li>
            <li><strong>Thermal Comfort:</strong> ${metadata?.thermal_comfort ?? 'Not reported'}</li>
            <li><strong>Overall Session Rating:</strong> ${metadata?.session_rating ?? 'Not reported'}</li>
          </ul>
          ${linkedPatient ? `
          <h2>Patient Health & Demographic Profile</h2>
          <ul>
            <li><strong>Age:</strong> ${linkedPatient.age_years ?? 'N/A'}</li>
            <li><strong>Height / Weight:</strong> ${linkedPatient.height_cm ?? 'N/A'} cm / ${linkedPatient.weight_kg ?? 'N/A'} kg</li>
            <li><strong>VR Experience:</strong> ${linkedPatient.vr_experience_level ?? 'N/A'}</li>
            <li><strong>Motion Sickness Susceptibility:</strong> ${linkedPatient.motion_sickness_susceptibility ?? 'N/A'}</li>
            <li><strong>Relevant Health Conditions:</strong> ${linkedPatient.relevant_health_conditions ?? 'None reported'}</li>
          </ul>` : ''}
    ` : `<p style="color:#94a3b8;font-size:13px;">Self-reported health & questionnaire data excluded from this export (not opted in).</p>`;

    const reportHtml = `
      <html>
        <head>
          <title>VRTelemetry Research Report</title>
          <style>
            body { font-family: system-ui, -apple-system, sans-serif; color: #1e293b; line-height: 1.5; max-width: 800px; margin: 40px auto; }
            h1 { color: #3b82f6; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }
            h2 { color: #334155; margin-top: 30px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }
            .grid { display: flex; gap: 40px; margin-bottom: 30px; }
            .box { background: #f8fafc; padding: 20px; border-radius: 8px; flex: 1; border: 1px solid #e2e8f0; }
            .label { font-size: 12px; color: #64748b; text-transform: uppercase; font-weight: bold; }
            .value { font-size: 24px; font-weight: 600; margin-top: 5px; }
            .footer-note { margin-top: 50px; font-size: 11px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 12px; }
          </style>
        </head>
        <body>
          <h1>Session Diagnostics Report</h1>
          <p><strong>Source File:</strong> ${metadata?.filename}</p>
          <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>

          <div class="grid">
            <div class="box"><div class="label">Session Duration</div><div class="value">${metadata?.duration_sec.toFixed(1)}s</div></div>
            <div class="box"><div class="label">Total Samples</div><div class="value">${metadata?.total_frames.toLocaleString()}</div></div>
            <div class="box"><div class="label">Avg Frequency</div><div class="value">${metadata?.avg_sampling_hz.toFixed(1)} Hz</div></div>
          </div>

          <h2>Biophysical Findings</h2>
          <ul>
            <li><strong>Tracking Quality (HMD):</strong> ${metadata?.hmd_validity_pct.toFixed(1)}%</li>
            <li><strong>Tracking Quality (Eye):</strong> ${metadata?.eye_validity_pct.toFixed(1)}%</li>
            <li><strong>Est. Focus Ratio:</strong> ${metrics?.focus_ratio.toFixed(1)}%</li>
            <li><strong>Average Head Speed:</strong> ${metrics?.avg_head_speed.toFixed(2)} m/s</li>
            <li><strong>Mean Pupil Diameter:</strong> ${metrics?.mean_pupil_diameter.toFixed(2)} mm</li>
            <li><strong>Mean Heart Rate:</strong> ${metrics?.hr_mean.toFixed(1)} BPM</li>
          </ul>

          <h2>Cognitive Load</h2>
          <p>${sm.cognitive_load.interpretation}</p>

          <h2>Vestibular Function & Postural Stability</h2>
          <p>${sm.postural_stability.interpretation}</p>

          <h2>Motor Function & Kinematics</h2>
          <p>${sm.motor_kinematics.interpretation}</p>

          <h2>Physical Exertion</h2>
          <p>${sm.exertion_profile.interpretation}</p>

          ${healthSection}

          <p class="footer-note">
            Generated by VRTelemetry Research Studio. This export ${includeHealthData ? 'includes' : 'excludes'} self-reported
            special-category health data, per the researcher's explicit opt-in at export time. Confirmed authorized
            research/clinical purpose at export: Yes. Derived scientific measures (cognitive load, postural stability,
            motor kinematics, exertion) are research-support indices, not validated clinical diagnostics.
          </p>
          <script>window.onload = () => window.print();</script>
        </body>
      </html>
    `;

    const printWindow = window.open('', '_blank');
    if (printWindow) {
      printWindow.document.write(reportHtml);
      printWindow.document.close();
    }
  };

  if (!metadata) return (
    <div className="flex h-full items-center justify-center text-[13px] text-ink-3">
      Load a Parquet session to enable exports.
    </div>
  );

  const exports: {
    key: string;
    tone: string;
    icon: React.ElementType;
    title: string;
    note: string;
    onClick: () => void;
    disabled: boolean;
    tag?: React.ReactNode;
    action: string;
  }[] = [
    {
      key: 'raw', tone: 'tone-1', icon: FileSpreadsheet,
      title: 'Raw Telemetry (CSV)',
      note: 'Every recorded frame, quote-escaped for safe re-import.',
      onClick: handleExportCSV, disabled: !canExport, action: 'Export',
      tag: <span className="mono text-[11px] text-ink-3">{frames.length.toLocaleString()} rows</span>,
    },
    {
      key: 'summary', tone: 'tone-3', icon: FileSpreadsheet,
      title: 'Session & Derived Metrics (CSV)',
      note: 'One row: full session record + every science metric — ideal for building a cohort spreadsheet across sessions.',
      onClick: handleExportSummaryCSV, disabled: !canExport, action: 'Export',
      tag: <span className="mono text-[11px] text-ink-3">1 row</span>,
    },
    {
      key: 'json', tone: 'tone-5', icon: FileJson,
      title: 'Full Analysis (JSON)',
      note: 'Session record, derived metrics, and all four science-metric domains.',
      onClick: handleExportJSON, disabled: !canExport, action: 'Export',
    },
    {
      key: 'report', tone: 'tone-2', icon: FileText,
      title: 'Scientific Report (PDF)',
      note: 'Printable summary covering all four research domains plus questionnaire results.',
      onClick: handleExportReport, disabled: !canExport, action: 'Export',
      tag: questionnaireMissing
        ? <span className="text-[11px]" style={{ color: 'var(--s4)' }}>questionnaire missing</span>
        : undefined,
    },
    {
      key: 'sync', tone: 'tone-6', icon: Upload,
      title: 'Sync to Central Server',
      note: isSyncing
        ? 'Syncing pending sessions and patients…'
        : syncStatus && syncStatus.pending_count > 0
          ? `${syncStatus.pending_sessions ?? 0} session(s), ${syncStatus.pending_patients ?? 0} patient(s) awaiting upload`
          : 'All sessions and patients synced',
      onClick: handleSyncNow, disabled: isSyncing, action: 'Sync',
    },
  ];

  const context: [string, React.ReactNode][] = [
    ['Source', <span key="a" className="mono block max-w-[190px] truncate text-[11.5px]" title={metadata.filename}>{metadata.filename}</span>],
    ['Frames', <span key="b" className="mono text-[11.5px]">{frames.length.toLocaleString()}</span>],
    ['Duration', <span key="c" className="mono text-[11.5px]">{metadata.duration_sec.toFixed(2)} s</span>],
    ['Channels', <span key="d" className="mono text-[11.5px]">{metadata.channels_detected.length}</span>],
    ['Health data included', (
      <span key="e" className="mono flex items-center gap-1 text-[11.5px]" style={{ color: includeHealthData ? 'var(--s6)' : 'var(--ink-3)' }}>
        {includeHealthData ? <Check className="h-3.5 w-3.5" /> : null} {includeHealthData ? 'Yes' : 'No'}
      </span>
    )],
  ];

  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-4">
      <div>
        <h1 className="page-title">Data Export &amp; Reports</h1>
        <p className="page-sub">
          Serialise the active session for statistical analysis, archival, or central sync.
        </p>
      </div>

      {patientConsentBlocked && (
        <div className="notice tone-2 items-start" role="alert">
          <ShieldAlert className="mt-0.5 h-4 w-4 flex-none text-tone" />
          <p className="m-0 flex-1 text-[13px] text-ink-2">
            This session's linked patient has withdrawn or erased GDPR consent. Export is disabled for this session
            until a valid consented record exists.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-3.5">

          <div className="clay p-4">
            <div className="section-head">
              <h2 className="section-title">Privacy scope</h2>
              <div className="section-rule" />
            </div>
            <div className="well flex flex-col gap-3 p-3.5">
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 flex-none cursor-pointer"
                  style={{ accentColor: 'var(--s1)' }}
                  checked={purposeConsent}
                  onChange={e => setPurposeConsent(e.target.checked)}
                  disabled={patientConsentBlocked}
                />
                <div>
                  <div className="text-[12.5px] font-medium">
                    Authorized research/clinical purpose <span style={{ color: 'var(--s2)' }}>*</span>
                  </div>
                  <p className="m-0 mt-1 text-[11.5px] leading-relaxed text-ink-3">
                    I confirm this export complies with the applicable GDPR legal basis and the subject's consent.
                  </p>
                </div>
              </label>

              <div style={{ height: 1, background: 'var(--well-line)' }} />

              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 flex-none cursor-pointer"
                  style={{ accentColor: 'var(--s1)' }}
                  checked={includeHealthData}
                  onChange={e => setIncludeHealthData(e.target.checked)}
                  disabled={!purposeConsent || patientConsentBlocked}
                />
                <div>
                  <div className="text-[12.5px] font-medium">Include self-reported health profile</div>
                  <p className="m-0 mt-1 text-[11.5px] leading-relaxed text-ink-3">
                    Special-category data, included in JSON/summary/report exports only. Off by default — raw
                    telemetry exports never include it regardless.
                  </p>
                </div>
              </label>
            </div>
          </div>

          <div className="clay flex flex-col gap-2.5 p-4">
            {exports.map(item => (
              <div key={item.key} className={`well flex items-center gap-3.5 p-3.5 ${item.tone}`}>
                <div className="icon-tile"><item.icon className="h-4 w-4" /></div>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium">{item.title}</div>
                  <p className="m-0 mt-1 text-[11.5px] leading-relaxed text-ink-3">{item.note}</p>
                </div>
                {item.tag}
                <button onClick={item.onClick} disabled={item.disabled} className="btn-clay flex-none">
                  <Download className="h-3.5 w-3.5" /> {item.action}
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3.5">
          <div className="clay p-4">
            <div className="section-head">
              <h2 className="section-title">Export context</h2>
              <div className="section-rule" />
            </div>
            <div className="well flex flex-col gap-2.5 p-3">
              {context.map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-3 text-[12px]">
                  <span className="flex-none text-ink-3">{label}</span>
                  {value}
                </div>
              ))}
            </div>
          </div>

          {!canExport && (
            <div className="notice tone-4 items-start">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" />
              <p className="m-0 flex-1 text-[12px] leading-relaxed text-ink-2">
                {patientConsentBlocked
                  ? 'Export blocked — patient consent is not active.'
                  : 'Confirm the purpose/consent checkbox to enable exports.'}
              </p>
            </div>
          )}

          {questionnaireMissing && (
            <div className="notice tone-4 items-start">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" />
              <p className="m-0 flex-1 text-[12px] leading-relaxed text-ink-2">
                NASA-TLX and SSQ fields will export empty until the post-session questionnaire is recorded.
              </p>
            </div>
          )}

          {isExporting && (
            <div className="clay-press px-4 py-3 text-center text-[12px] text-ink-2">Generating files…</div>
          )}
        </div>
      </div>
    </div>
  );
};
