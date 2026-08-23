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
  
  right_pos_x?: number; right_pos_y?: number; right_pos_z?: number;
  right_rot_x?: number; right_rot_y?: number; right_rot_z?: number; right_rot_w?: number;
}

export interface SessionMetadata {
  filename: string;
  duration_sec: number;
  total_frames: number;
  channels_detected: string[];
  hmd_validity_pct: number;
  eye_validity_pct: number;
  avg_sampling_hz: number;
}

export interface DerivedMetrics {
  focus_ratio: number;
  avg_head_speed: number;
  fixation_count: number;
  mean_pupil_diameter: number;
  hr_mean: number;
}