import type { TelemetryFrame, SessionMetadata, DerivedMetrics } from '../types/telemetry';

export class TelemetryParser {
  static async parseFile(file: File): Promise<{ frames: TelemetryFrame[], metadata: SessionMetadata, metrics: DerivedMetrics }> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('http://localhost:8000/api/upload-telemetry', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Szerver hiba történt a fájl feldolgozásakor: ${response.statusText}`);
    }

    const data = await response.json();
    
    const frames = data.frames as TelemetryFrame[];
    const colNames = data.columns as string[];
    const originalFrameCount = data.original_frames as number;

    return this.processData(frames, file.name, colNames, originalFrameCount);
  }

  /**
   * Loads a previously recorded session straight from the local backend by
   * session_id (GET /api/sessions/{id}/telemetry), instead of requiring the
   * researcher to manually drag-drop the .parquet file. This is what makes
   * "View Details" / "Load for Analysis" in Session Explorer actually work —
   * before this existed, browsing to a session there never loaded its
   * telemetry into any analysis page. Also merges in the real session_metadata
   * DB row (calibration/anthropometrics + questionnaire scores), which a raw
   * dropped file can never carry since that data doesn't live in the Parquet.
   */
  static async parseSessionId(sessionId: string): Promise<{ frames: TelemetryFrame[], metadata: SessionMetadata, metrics: DerivedMetrics }> {
    const response = await fetch(`http://localhost:8000/api/sessions/${sessionId}/telemetry`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Failed to load session ${sessionId}`);
    }
    const data = await response.json();
    const frames = data.frames as TelemetryFrame[];
    const colNames = data.columns as string[];
    const originalFrameCount = data.original_frames as number;

    const result = this.processData(frames, `${sessionId}.parquet`, colNames, originalFrameCount);
    return { ...result, metadata: this.mergeSessionRecord(result.metadata, data.session_record) };
  }

  /** Maps session_metadata's DB column names onto the SessionMetadata shape the rest of the app reads. */
  private static mergeSessionRecord(metadata: SessionMetadata, record: Record<string, any> | undefined): SessionMetadata {
    if (!record) return metadata;
    return {
      ...metadata,
      session_id: record.session_id ?? metadata.session_id,
      patient_id: record.patient_id ?? metadata.patient_id,
      subject_id: record.subject_id || metadata.subject_id,
      hmd_model: record.hmd_model || metadata.hmd_model,
      subject_ipd_mm: record.subject_ipd_mm || metadata.subject_ipd_mm,
      total_dropped_frames: record.total_dropped_frames ?? metadata.total_dropped_frames,
      height_cm: record.subject_height_cm || undefined,
      weight_kg: record.subject_weight_kg || undefined,
      age_years: record.subject_age || undefined,
      dominant_hand: record.dominant_hand || undefined,
      arm_length_left: record.arm_length_left || undefined,
      arm_length_right: record.arm_length_right || undefined,
      shoulder_width_est: record.shoulder_width_est || undefined,
      neutral_head_height: record.neutral_head_height || undefined,
      nasa_tlx_mental: record.nasa_tlx_mental || undefined,
      nasa_tlx_physical: record.nasa_tlx_physical || undefined,
      nasa_tlx_temporal: record.nasa_tlx_temporal || undefined,
      nasa_tlx_performance: record.nasa_tlx_performance || undefined,
      nasa_tlx_effort: record.nasa_tlx_effort || undefined,
      nasa_tlx_frustration: record.nasa_tlx_frustration || undefined,
      nasa_tlx_rtlx: record.nasa_tlx_rtlx || undefined,
      nasa_tlx_band: record.nasa_tlx_band || undefined,
      ssq_nausea_score: record.ssq_nausea_score || undefined,
      ssq_oculomotor_score: record.ssq_oculomotor_score || undefined,
      ssq_disorientation: record.ssq_disorientation || undefined,
      ssq_total_severity: record.ssq_total_severity || undefined,
      ssq_severity_band: record.ssq_severity_band || undefined,
      thermal_comfort: record.thermal_comfort || undefined,
      perceived_temp_c: record.perceived_temp_c || undefined,
      session_rating: record.session_rating || undefined,
      questionnaire_completed_at: record.questionnaire_completed_at ?? null,
    };
  }

  /**
   * The raw Parquet file carries no subject/hardware record (that lives in the
   * SQLite session table, keyed off a session UUID we don't have here when a
   * file is dropped in directly). Best-effort recovery from the filename itself.
   */
  private static extractSubjectId(filename: string): string {
    const subMatch = filename.match(/SUB[_-]?[A-Za-z0-9]+/i);
    if (subMatch) return subMatch[0].toUpperCase();

    const sessionMatch = filename.match(/vr_telemetry_(\d{8}_\d{6})/i);
    if (sessionMatch) return `SESSION_${sessionMatch[1]}`;

    return filename.replace(/\.[^/.]+$/, '');
  }

  /**
   * Heuristic HMD/driver detection based on how each eye-tracking driver
   * populates left_pupil_size (see src/eye_tracking/*.py):
   *  - EXTEyeGazeDriver explicitly writes -1.0 (unsupported sentinel)
   *  - FBEyeTrackingSocialDriver overloads the field with a 0-1 confidence value
   *  - HTCEyeTrackingDriver overloads it with a 0-1 (1 - blink) value
   * We can't fully disambiguate FB vs HTC from the value range alone, so we
   * report the pair together rather than fabricate a specific model name.
   */
  private static inferHmdModel(frames: TelemetryFrame[]): string {
    const sample = frames.find(f => f.eye_tracking_valid > 0);
    if (!sample) return 'Unknown HMD (No Eye Tracking Signal)';

    if (sample.left_pupil_size === -1 || sample.right_pupil_size === -1) {
      return 'Generic OpenXR HMD (EXT Eye Gaze — No Pupillometry)';
    }
    if (sample.left_pupil_size >= 0 && sample.left_pupil_size <= 1) {
      return 'Meta Quest Pro / HTC (Biometric Eye Tracking)';
    }
    return 'OpenXR-Compatible HMD';
  }

  private static processData(frames: TelemetryFrame[], filename: string, channels: string[], originalFrameCount: number) {
    let hmdValid = 0;
    let hmdDropped = 0;
    let eyeValid = 0;
    let totalSpeed = 0;
    let fixationFrames = 0;
    let hrSum = 0;
    let hrCount = 0;
    let pupilSum = 0;
    let pupilCount = 0;

    let ipdSum = 0;
    let ipdCount = 0;

    let peakSaccade = 0;

    let handSpeedSum = 0;
    let handSpeedSamples = 0;

    for (let i = 0; i < frames.length; i++) {
      const f = frames[i];

      if (f.hmd_tracking_valid > 0) hmdValid++;
      else hmdDropped++;

      if (f.eye_tracking_valid > 0) eyeValid++;

      if (f.heart_rate_bpm > 0) {
        hrSum += f.heart_rate_bpm;
        hrCount++;
      }

      if (f.left_pupil_size > 0 && f.right_pupil_size > 0) {
        pupilSum += (f.left_pupil_size + f.right_pupil_size) / 2;
        pupilCount++;
      }

      // Inter-pupillary distance estimate from binocular eye positions.
      // Sanity-bound to plausible physiological IPD range to reject spatial outliers.
      if (f.eye_tracking_valid > 0) {
        const edx = f.right_eye_pos_x - f.left_eye_pos_x;
        const edy = f.right_eye_pos_y - f.left_eye_pos_y;
        const edz = f.right_eye_pos_z - f.left_eye_pos_z;
        const eyeDist = Math.sqrt(edx * edx + edy * edy + edz * edz);
        if (eyeDist > 0.02 && eyeDist < 0.2) {
          ipdSum += eyeDist;
          ipdCount++;
        }
      }

      if (i > 0) {
        const prev = frames[i - 1];
        const dt = (f.timestamp_ns - prev.timestamp_ns) / 1e9;

        // Head kinematics / fixation detection (existing logic)
        if (f.hmd_tracking_valid > 0 && prev.hmd_tracking_valid > 0 && dt > 0) {
          const dx = f.hmd_pos_x - prev.hmd_pos_x;
          const dy = f.hmd_pos_y - prev.hmd_pos_y;
          const dz = f.hmd_pos_z - prev.hmd_pos_z;
          const speed = Math.sqrt(dx * dx + dy * dy + dz * dz) / dt;
          totalSpeed += speed;

          if (speed < 0.15 && f.eye_tracking_valid > 0) {
            fixationFrames++;
          }
        }

        // Peak saccadic (gaze) angular velocity — quaternion delta magnitude
        if (f.eye_tracking_valid > 0 && prev.eye_tracking_valid > 0) {
          const dqx = f.left_eye_rot_x - prev.left_eye_rot_x;
          const dqy = f.left_eye_rot_y - prev.left_eye_rot_y;
          const dqz = f.left_eye_rot_z - prev.left_eye_rot_z;
          const dqw = f.left_eye_rot_w - prev.left_eye_rot_w;
          const gazeShift = Math.sqrt(dqx * dqx + dqy * dqy + dqz * dqz + dqw * dqw) * 100;
          if (gazeShift > peakSaccade) peakSaccade = gazeShift;
        }

        // Bimanual controller (hand) kinematics
        if (dt > 0) {
          if (
            f.left_pos_x !== undefined && prev.left_pos_x !== undefined &&
            (f.left_tracking_valid ?? 1) > 0 && (prev.left_tracking_valid ?? 1) > 0
          ) {
            const dx = f.left_pos_x - prev.left_pos_x;
            const dy = (f.left_pos_y ?? 0) - (prev.left_pos_y ?? 0);
            const dz = (f.left_pos_z ?? 0) - (prev.left_pos_z ?? 0);
            const speed = Math.sqrt(dx * dx + dy * dy + dz * dz) / dt;
            if (speed < 10) { // reject teleport/init-frame outliers
              handSpeedSum += speed;
              handSpeedSamples++;
            }
          }
          if (
            f.right_pos_x !== undefined && prev.right_pos_x !== undefined &&
            (f.right_tracking_valid ?? 1) > 0 && (prev.right_tracking_valid ?? 1) > 0
          ) {
            const dx = f.right_pos_x - prev.right_pos_x;
            const dy = (f.right_pos_y ?? 0) - (prev.right_pos_y ?? 0);
            const dz = (f.right_pos_z ?? 0) - (prev.right_pos_z ?? 0);
            const speed = Math.sqrt(dx * dx + dy * dy + dz * dz) / dt;
            if (speed < 10) {
              handSpeedSum += speed;
              handSpeedSamples++;
            }
          }
        }
      }
    }

    const durationSec = (frames[frames.length - 1].timestamp_ns - frames[0].timestamp_ns) / 1e9;

    const metadata: SessionMetadata = {
      filename,
      duration_sec: durationSec,
      total_frames: originalFrameCount, 
      channels_detected: channels,
      hmd_validity_pct: (hmdValid / frames.length) * 100,
      eye_validity_pct: (eyeValid / frames.length) * 100,
      avg_sampling_hz: originalFrameCount / durationSec,

      subject_id: this.extractSubjectId(filename),
      hmd_model: this.inferHmdModel(frames),
      subject_ipd_mm: ipdCount > 0 ? (ipdSum / ipdCount) * 1000 : undefined,
      total_dropped_frames: hmdDropped,
    };

    const metrics: DerivedMetrics = {
      focus_ratio: (fixationFrames / frames.length) * 100,
      avg_head_speed: totalSpeed / frames.length,
      fixation_count: fixationFrames,
      hr_mean: hrCount > 0 ? hrSum / hrCount : 0,
      mean_pupil_diameter: pupilCount > 0 ? pupilSum / pupilCount : 0,

      peak_saccade: peakSaccade,
      avg_hand_speed: handSpeedSamples > 0 ? handSpeedSum / handSpeedSamples : 0,
    };

    return { frames, metadata, metrics };
  }
}