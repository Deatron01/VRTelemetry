// src/frontend/VRTelemetry/src/pages/Export.tsx

import React, { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { Download, FileJson, FileSpreadsheet, FileText, Check, Upload, ShieldAlert, AlertCircle, Video } from 'lucide-react';
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
  const [avStatus, setAvStatus] = useState<any>(null);

  useEffect(() => {
    fetch('http://localhost:8000/api/sync/status')
      .then(r => r.json())
      .then(setSyncStatus)
      .catch(() => setSyncStatus(null));
  }, []);

  useEffect(() => {
    if (!metadata?.session_id) { setAvStatus(null); return; }
    fetch(`http://localhost:8000/api/sessions/${metadata.session_id}/av-recording`)
      .then(r => r.ok ? r.json() : null)
      .then(setAvStatus)
      .catch(() => setAvStatus(null));
  }, [metadata?.session_id]);

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

  const handleExportReport = async () => {
    if (!canExport) return;
    const sm = scienceMetrics();

    // Generate QR code for parquet download URL
    let qrCodeDataUrl = '';
    try {
      const downloadUrl = metadata?.session_id
        ? `http://localhost:8000/api/sessions/${metadata.session_id}/download`
        : `No remote session linked (${metadata?.filename})`;

      qrCodeDataUrl = await QRCode.toDataURL(downloadUrl, {
        width: 120,
        margin: 0,
        color: { dark: '#1e293b', light: '#ffffff' }
      });
    } catch (e) {
      console.error('Failed to generate QR code', e);
    }

    const healthSection = includeHealthData ? `
          <h2 class="section-title health-title">Subjective Questionnaire & Patient Profile</h2>
          <div class="metrics-grid">
            <div class="metric-box">
              <div class="label">NASA-TLX (RTLX)</div>
              <div class="value">${metadata?.nasa_tlx_rtlx?.toFixed(1) ?? 'N/A'} <span class="band">${metadata?.nasa_tlx_band ? `(${metadata.nasa_tlx_band})` : ''}</span></div>
            </div>
            <div class="metric-box">
              <div class="label">SSQ Total Severity</div>
              <div class="value">${metadata?.ssq_total_severity?.toFixed(1) ?? 'N/A'} <span class="band">${metadata?.ssq_severity_band ? `(${metadata.ssq_severity_band})` : ''}</span></div>
            </div>
            <div class="metric-box">
              <div class="label">Thermal Comfort</div>
              <div class="value">${metadata?.thermal_comfort ?? 'N/A'}</div>
            </div>
            <div class="metric-box">
              <div class="label">Session Rating</div>
              <div class="value">${metadata?.session_rating ?? 'N/A'}</div>
            </div>
          </div>

          <table class="data-table mt-4">
            <thead>
              <tr><th>Subscale</th><th>Score</th></tr>
            </thead>
            <tbody>
              <tr><td>Mental Demand</td><td>${metadata?.nasa_tlx_mental ?? 'N/A'}</td></tr>
              <tr><td>Physical Demand</td><td>${metadata?.nasa_tlx_physical ?? 'N/A'}</td></tr>
              <tr><td>Temporal Demand</td><td>${metadata?.nasa_tlx_temporal ?? 'N/A'}</td></tr>
              <tr><td>Performance</td><td>${metadata?.nasa_tlx_performance ?? 'N/A'}</td></tr>
              <tr><td>Effort</td><td>${metadata?.nasa_tlx_effort ?? 'N/A'}</td></tr>
              <tr><td>Frustration</td><td>${metadata?.nasa_tlx_frustration ?? 'N/A'}</td></tr>
              <tr><td>SSQ Nausea</td><td>${metadata?.ssq_nausea_score?.toFixed(1) ?? 'N/A'}</td></tr>
              <tr><td>SSQ Oculomotor</td><td>${metadata?.ssq_oculomotor_score?.toFixed(1) ?? 'N/A'}</td></tr>
              <tr><td>SSQ Disorientation</td><td>${metadata?.ssq_disorientation?.toFixed(1) ?? 'N/A'}</td></tr>
            </tbody>
          </table>

          ${linkedPatient ? `
          <h3 style="margin-top:20px; font-size:16px;">Patient Demographic Profile</h3>
          <table class="data-table">
            <tbody>
              <tr><td style="width: 200px"><strong>Age</strong></td><td>${linkedPatient.age_years ?? 'N/A'}</td></tr>
              <tr><td><strong>Height / Weight</strong></td><td>${linkedPatient.height_cm ?? 'N/A'} cm / ${linkedPatient.weight_kg ?? 'N/A'} kg</td></tr>
              <tr><td><strong>VR Experience</strong></td><td>${linkedPatient.vr_experience_level ?? 'N/A'}</td></tr>
              <tr><td><strong>Motion Sickness Susceptibility</strong></td><td>${linkedPatient.motion_sickness_susceptibility ?? 'N/A'}</td></tr>
              <tr><td><strong>Relevant Health Conditions</strong></td><td>${linkedPatient.relevant_health_conditions || 'None reported'}</td></tr>
            </tbody>
          </table>` : ''}
    ` : `<p class="omitted-note">Self-reported health & questionnaire data excluded from this export (not opted in).</p>`;

    const reportHtml = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>VRTelemetry Research Report</title>
          <style>
            :root {
              --c-text: #0f172a; --c-text-muted: #64748b;
              --c-border: #e2e8f0; --c-bg-subtle: #f8fafc;
              --c-primary: #3b82f6; --c-cognitive: #10b981;
              --c-vestibular: #f59e0b; --c-motor: #8b5cf6; --c-exertion: #ef4444;
            }
            body { font-family: system-ui, -apple-system, sans-serif; color: var(--c-text); line-height: 1.5; max-width: 850px; margin: 0 auto; padding: 40px; font-size: 14px; }

            /* Header */
            .header-container { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid var(--c-primary); padding-bottom: 20px; margin-bottom: 30px; }
            .header-info h1 { margin: 0 0 10px 0; color: var(--c-primary); font-size: 28px; }
            .header-info p { margin: 4px 0; color: var(--c-text-muted); }
            .header-qr { text-align: center; }
            .header-qr img { width: 100px; height: 100px; display: block; margin: 0 auto; }
            .header-qr p { font-size: 10px; color: var(--c-text-muted); margin-top: 5px; max-width: 120px; line-height: 1.2; }

            /* Sections */
            .section { margin-bottom: 40px; break-inside: avoid; }
            .section-title { font-size: 18px; margin: 0 0 15px 0; padding-bottom: 8px; border-bottom: 1px solid var(--c-border); color: var(--c-text); display: flex; align-items: center; }
            .section-title::before { content: ""; display: inline-block; width: 4px; height: 18px; margin-right: 10px; border-radius: 2px; }

            .bio-title::before { background: var(--c-primary); }
            .cog-title::before { background: var(--c-cognitive); }
            .vest-title::before { background: var(--c-vestibular); }
            .motor-title::before { background: var(--c-motor); }
            .exer-title::before { background: var(--c-exertion); }
            .health-title::before { background: #64748b; }

            /* Grids & Metrics */
            .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 15px; }
            .metric-box { background: var(--c-bg-subtle); padding: 15px; border-radius: 6px; border: 1px solid var(--c-border); }
            .metric-box .label { font-size: 11px; color: var(--c-text-muted); text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; }
            .metric-box .value { font-size: 20px; font-weight: 600; margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
            .metric-box .band { font-size: 12px; font-weight: normal; color: var(--c-text-muted); font-family: system-ui; }

            /* Tables */
            .data-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: 13px; }
            .data-table th, .data-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--c-border); }
            .data-table th { background: var(--c-bg-subtle); font-weight: 600; color: var(--c-text-muted); font-size: 12px; text-transform: uppercase; }
            .data-table tbody tr:nth-child(even) { background: #fafafa; }

            .interp-box { background: #f0f9ff; border-left: 3px solid var(--c-primary); padding: 12px 16px; font-size: 13.5px; color: #0f172a; margin-top: 15px; border-radius: 0 4px 4px 0; }
            .omitted-note { color: var(--c-text-muted); font-size: 13px; font-style: italic; background: var(--c-bg-subtle); padding: 15px; border-radius: 6px; text-align: center; }
            .mt-4 { margin-top: 16px; }

            /* Footer */
            .footer-note { margin-top: 50px; font-size: 11px; color: var(--c-text-muted); border-top: 1px solid var(--c-border); padding-top: 15px; line-height: 1.6; }

            @media print {
              body { padding: 0; max-width: 100%; }
              .header-container { margin-bottom: 20px; }
              .section { margin-bottom: 25px; }
              @page { margin: 1.5cm; }
            }
          </style>
        </head>
        <body>
          <div class="header-container">
            <div class="header-info">
              <h1>Scientific Session Report</h1>
              <p><strong>Source File:</strong> ${metadata?.filename}</p>
              <p><strong>Session ID:</strong> ${metadata?.session_id || 'Unlinked local file'}</p>
              <p><strong>Subject ID:</strong> ${metadata?.subject_id || 'N/A'}</p>
              <p><strong>Generated:</strong> ${new Date().toLocaleString()}</p>
            </div>
            <div class="header-qr">
              ${qrCodeDataUrl ? `<img src="${qrCodeDataUrl}" alt="QR Code" />` : ''}
              <p>Scan to download session data (.parquet)</p>
            </div>
          </div>

          <div class="section">
            <div class="metrics-grid">
              <div class="metric-box"><div class="label">Session Duration</div><div class="value">${metadata?.duration_sec.toFixed(1)}s</div></div>
              <div class="metric-box"><div class="label">Total Samples</div><div class="value">${metadata?.total_frames.toLocaleString()}</div></div>
              <div class="metric-box"><div class="label">Avg Frequency</div><div class="value">${metadata?.avg_sampling_hz.toFixed(1)} Hz</div></div>
              <div class="metric-box"><div class="label">Device</div><div class="value" style="font-family: inherit; font-size: 16px;">${metadata?.hmd_model || 'Unknown'}</div></div>
            </div>
          </div>

          <div class="section">
            <h2 class="section-title bio-title">Biophysical Summary</h2>
            <table class="data-table">
              <thead>
                <tr><th>Metric</th><th>Value</th><th>Unit</th></tr>
              </thead>
              <tbody>
                <tr><td><strong>HMD Tracking Quality</strong></td><td>${metadata?.hmd_validity_pct.toFixed(1)}</td><td>% valid frames</td></tr>
                <tr><td><strong>Eye Tracking Quality</strong></td><td>${metadata?.eye_validity_pct.toFixed(1)}</td><td>% valid frames</td></tr>
                <tr><td><strong>Est. Focus Ratio</strong></td><td>${metrics?.focus_ratio.toFixed(1)}</td><td>% of session</td></tr>
                <tr><td><strong>Average Head Speed</strong></td><td>${metrics?.avg_head_speed.toFixed(3)}</td><td>m/s</td></tr>
                <tr><td><strong>Mean Pupil Diameter</strong></td><td>${metrics?.mean_pupil_diameter.toFixed(2)}</td><td>mm</td></tr>
                <tr><td><strong>Mean Heart Rate</strong></td><td>${metrics?.hr_mean.toFixed(1)}</td><td>BPM</td></tr>
              </tbody>
            </table>
          </div>

          <div class="section">
            <h2 class="section-title cog-title">Cognitive Load & Mental Workload</h2>
            <div class="metrics-grid">
              <div class="metric-box"><div class="label">Mean TEPR</div><div class="value">+${sm.cognitive_load.meanTepr.toFixed(1)}%</div></div>
              <div class="metric-box"><div class="label">Peak TEPR</div><div class="value">+${sm.cognitive_load.peakTepr.toFixed(1)}%</div></div>
              <div class="metric-box"><div class="label">Peak Time</div><div class="value">${sm.cognitive_load.peakTime.toFixed(1)}s</div></div>
              <div class="metric-box"><div class="label">Base Pupil</div><div class="value">${sm.cognitive_load.globalBaselinePupil.toFixed(2)}mm</div></div>
            </div>
            <div class="interp-box" style="border-left-color: var(--c-cognitive)">
              ${sm.cognitive_load.interpretation}
            </div>
          </div>

          <div class="section">
            <h2 class="section-title vest-title">Vestibular Function & Postural Stability</h2>
            <table class="data-table">
              <thead>
                <tr><th>Metric</th><th>Value</th><th>Unit</th></tr>
              </thead>
              <tbody>
                <tr><td>Total Sway Path Length</td><td>${sm.postural_stability.totalPathLengthM.toFixed(3)}</td><td>meters</td></tr>
                <tr><td>Mean Sway Velocity</td><td>${sm.postural_stability.meanSwayVelocity.toFixed(4)}</td><td>m/s</td></tr>
                <tr><td>95% Sway Ellipse Area</td><td>${sm.postural_stability.swayEllipseAreaM2.toFixed(5)}</td><td>m²</td></tr>
                <tr><td>Low-Frequency Energy Ratio (<0.5Hz)</td><td>${(sm.postural_stability.lowFrequencyEnergyRatio * 100).toFixed(1)}</td><td>%</td></tr>
              </tbody>
            </table>
            <div class="interp-box" style="border-left-color: var(--c-vestibular)">
              ${sm.postural_stability.interpretation}
            </div>
          </div>

          <div class="section">
            <h2 class="section-title motor-title">Motor Function & Kinematics</h2>
            <table class="data-table">
              <thead>
                <tr><th>Metric</th><th>Left Hand</th><th>Right Hand</th><th>Symmetry (Asym %)</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Normalized Jerk</td>
                  <td>${sm.motor_kinematics.left.normalizedJerk.toFixed(1)}</td>
                  <td>${sm.motor_kinematics.right.normalizedJerk.toFixed(1)}</td>
                  <td>-</td>
                </tr>
                <tr>
                  <td>Mean Speed (m/s)</td>
                  <td>${sm.motor_kinematics.left.meanSpeed.toFixed(3)}</td>
                  <td>${sm.motor_kinematics.right.meanSpeed.toFixed(3)}</td>
                  <td>${(sm.motor_kinematics.speedSymmetryIndex * 100).toFixed(1)}%</td>
                </tr>
                <tr>
                  <td>Max Reach (m)</td>
                  <td>${sm.motor_kinematics.left.maxReachM.toFixed(2)} ${sm.motor_kinematics.left.reachPctOfArmLength ? `(${sm.motor_kinematics.left.reachPctOfArmLength.toFixed(0)}% arm)` : ''}</td>
                  <td>${sm.motor_kinematics.right.maxReachM.toFixed(2)} ${sm.motor_kinematics.right.reachPctOfArmLength ? `(${sm.motor_kinematics.right.reachPctOfArmLength.toFixed(0)}% arm)` : ''}</td>
                  <td>${(sm.motor_kinematics.reachSymmetryIndex * 100).toFixed(1)}%</td>
                </tr>
              </tbody>
            </table>
            <div class="interp-box" style="border-left-color: var(--c-motor)">
              ${sm.motor_kinematics.interpretation}
            </div>
          </div>

          <div class="section">
            <h2 class="section-title exer-title">Physical Exertion</h2>
            <div class="metrics-grid">
              <div class="metric-box"><div class="label">Resting HR Est.</div><div class="value">${sm.exertion_profile.restingHrEstimate.toFixed(0)} <span class="band">BPM</span></div></div>
              <div class="metric-box"><div class="label">Peak HR</div><div class="value">${sm.exertion_profile.peakHr.toFixed(0)} <span class="band">BPM</span></div></div>
              <div class="metric-box"><div class="label">HR Drift</div><div class="value">${sm.exertion_profile.hrDriftBpm > 0 ? '+' : ''}${sm.exertion_profile.hrDriftBpm.toFixed(1)} <span class="band">BPM</span></div></div>
              <div class="metric-box"><div class="label">Exertion Index</div><div class="value">${sm.exertion_profile.exertionIndex.toFixed(0)}<span class="band">/100</span></div></div>
            </div>
            <div class="interp-box" style="border-left-color: var(--c-exertion)">
              ${sm.exertion_profile.interpretation}
            </div>
          </div>

          <div class="section">
            ${healthSection}
          </div>

          <p class="footer-note">
            Generated by VRTelemetry Research Studio. This export ${includeHealthData ? 'includes' : 'excludes'} self-reported
            special-category health data, per the researcher's explicit opt-in at export time. Confirmed authorized
            research/clinical purpose at export: Yes. Derived scientific measures (cognitive load, postural stability,
            motor kinematics, exertion) are research-support indices, not validated clinical diagnostics.
            VRTelemetry is not a medical device; this report is not a medical assessment or medical advice.
          </p>
          <script>
            // Slight delay to ensure images (QR code) are fully loaded before print
            window.onload = () => {
              setTimeout(() => { window.print(); }, 200);
            };
          </script>
        </body>
      </html>
    `;

    const printWindow = window.open('', '_blank');
    if (printWindow) {
      printWindow.document.write(reportHtml);
      printWindow.document.close();
    }
  };

  const handleExportVideo = () => {
    if (!canExport || !avStatus?.has_video || !metadata?.session_id) return;
    window.open(`http://localhost:8000/api/sessions/${metadata.session_id}/av-recording/video`, '_blank');
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
      key: 'video', tone: 'tone-4', icon: Video,
      title: 'Session Recording (MP4)',
      note: avStatus?.has_video ? 'Download the raw A/V recording of this session.' :
            avStatus?.video_deleted_at_utc ? 'Raw video has been deleted under the configured retention period.' :
            'No video recorded for this session.',
      onClick: handleExportVideo, disabled: !canExport || !avStatus?.has_video, action: 'Download',
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
