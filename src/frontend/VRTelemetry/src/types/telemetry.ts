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

  // Present when the recorder tags frames with the active scene/task. Used by
  // ScienceMetrics to baseline pupil size per scene (PLR-proxy compensation).
  scene_id?: number | string;
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
  // Populated by the post-session questionnaire (components/PostSessionQuestionnaire.tsx)
  // via POST /api/sessions/{id}/questionnaire, or left undefined until it's completed.
  nasa_tlx_mental?: number;
  nasa_tlx_physical?: number;
  nasa_tlx_temporal?: number;
  nasa_tlx_performance?: number;
  nasa_tlx_effort?: number;
  nasa_tlx_frustration?: number;
  nasa_tlx_rtlx?: number;
  nasa_tlx_band?: string;
  ssq_nausea_score?: number;
  ssq_oculomotor_score?: number;
  ssq_disorientation?: number;
  ssq_total_severity?: number;
  ssq_severity_band?: string;
  thermal_comfort?: string;
  perceived_temp_c?: number;
  session_rating?: number;
  questionnaire_completed_at?: string | null;

  // Present when the session was loaded via Session Explorer (backed by the
  // real session_metadata row) rather than a raw drag-dropped .parquet file —
  // arm length / shoulder width / neutral head height are the anthropometric
  // baseline used by ScienceMetrics to normalize kinematic reach & motion.
  session_id?: string;
  patient_id?: string | null;
  // Naive-UTC ISO string as stored (src/utils/clock.py::as_stored) — no
  // trailing "Z"/offset. Used by SessionVideoPanel to line up the recorded
  // screen capture's own start time against this session's telemetry clock;
  // must be parsed as UTC explicitly (see that file's parseNaiveUtcMs).
  start_timestamp_utc?: string;
  height_cm?: number;
  weight_kg?: number;
  age_years?: number;
  dominant_hand?: string;
  arm_length_left?: number;
  arm_length_right?: number;
  shoulder_width_est?: number;
  neutral_head_height?: number;
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
