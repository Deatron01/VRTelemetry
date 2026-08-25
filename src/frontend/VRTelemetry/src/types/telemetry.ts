export interface TelemetryFrame {
  frame_index: number;
  timestamp_ns: number;
  
  hmd_pos_x: number; hmd_pos_y: number; hmd_pos_z: number;
  hmd_rot_x: number; hmd_rot_y: number; hmd_rot_z: number; hmd_rot_w: number;
  
  left_eye_pos_x: number; left_eye_pos_y: number; left_eye_pos_z: number;
  left_eye_rot_x: number; left_eye_rot_y: number; left_eye_rot_z: number; left_eye_rot_w: number;
  
  right_eye_pos_x: number; right_eye_pos_y: number; right_eye_pos_z: number;
  right_eye_rot_x: number; right_eye_rot_y: number; right_eye_rot_z: number; right_eye_rot_w: number;
  
  hmd_tracking_valid: number;
  eye_tracking_valid: number;
  
  left_pupil_size: number;
  right_pupil_size: number;
  heart_rate_bpm: number;

  left_pos_x?: number; left_pos_y?: number; left_pos_z?: number;
  left_rot_x?: number; left_rot_y?: number; left_rot_z?: number; left_rot_w?: number;
  left_tracking_valid?: number;
  
  right_pos_x?: number; right_pos_y?: number; right_pos_z?: number;
  right_rot_x?: number; right_rot_y?: number; right_rot_z?: number; right_rot_w?: number;
  right_tracking_valid?: number;
}

export interface SessionMetadata {
  filename: string;
  duration_sec: number;
  total_frames: number;
  channels_detected: string[];
  hmd_validity_pct: number;
  eye_validity_pct: number;
  avg_sampling_hz: number;

  // Previously referenced in Overview.tsx but never populated — now computed by TelemetryParser
  subject_id?: string;
  hmd_model?: string;
  subject_ipd_mm?: number;
  total_dropped_frames?: number;

  // Genuinely subjective/self-reported values — not derivable from telemetry.
  // Left optional; populate via a post-session survey form when one exists.
  nasa_tlx_mental?: number;
  ssq_nausea_score?: number;
}

export interface DerivedMetrics {
  focus_ratio: number;
  avg_head_speed: number;
  fixation_count: number;
  mean_pupil_diameter: number;
  hr_mean: number;

  // Previously referenced in Overview.tsx but never populated — now computed by TelemetryParser
  peak_saccade?: number;
  avg_hand_speed?: number;
}