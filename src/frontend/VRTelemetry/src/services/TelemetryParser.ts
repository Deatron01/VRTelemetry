import type { TelemetryFrame, SessionMetadata, DerivedMetrics } from '../types/telemetry';

export class TelemetryParser {
  static async parseFile(file: File): Promise<{ frames: TelemetryFrame[], metadata: SessionMetadata, metrics: DerivedMetrics }> {
    const formData = new FormData();
    formData.append('file', file);

    // Fájl küldése a Python backendnek (lokálisan ez azonnali)
    // Ha a backend máshol fut, frissítsd az URL-t!
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

  private static processData(frames: TelemetryFrame[], filename: string, channels: string[], originalFrameCount: number) {
    let hmdValid = 0;
    let eyeValid = 0;
    let totalSpeed = 0;
    let fixationFrames = 0;
    let hrSum = 0;
    let hrCount = 0;
    let pupilSum = 0;
    let pupilCount = 0;

    for (let i = 0; i < frames.length; i++) {
      const f = frames[i];
      if (f.hmd_tracking_valid > 0) hmdValid++;
      if (f.eye_tracking_valid > 0) eyeValid++;
      
      if (f.heart_rate_bpm > 0) {
        hrSum += f.heart_rate_bpm;
        hrCount++;
      }

      if (f.left_pupil_size > 0 && f.right_pupil_size > 0) {
        pupilSum += (f.left_pupil_size + f.right_pupil_size) / 2;
        pupilCount++;
      }

      if (i > 0 && f.hmd_tracking_valid > 0 && frames[i-1].hmd_tracking_valid > 0) {
        const prev = frames[i-1];
        const dt = (f.timestamp_ns - prev.timestamp_ns) / 1e9;
        if (dt > 0) {
          const dx = f.hmd_pos_x - prev.hmd_pos_x;
          const dy = f.hmd_pos_y - prev.hmd_pos_y;
          const dz = f.hmd_pos_z - prev.hmd_pos_z;
          const speed = Math.sqrt(dx*dx + dy*dy + dz*dz) / dt;
          totalSpeed += speed;

          if (speed < 0.15 && f.eye_tracking_valid > 0) {
            fixationFrames++;
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
      avg_sampling_hz: originalFrameCount / durationSec 
    };

    const metrics: DerivedMetrics = {
      focus_ratio: (fixationFrames / frames.length) * 100,
      avg_head_speed: totalSpeed / frames.length,
      fixation_count: fixationFrames,
      hr_mean: hrCount > 0 ? hrSum / hrCount : 0,
      mean_pupil_diameter: pupilCount > 0 ? pupilSum / pupilCount : 0
    };

    return { frames, metadata, metrics };
  }
}