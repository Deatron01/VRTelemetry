import time
from dataclasses import dataclass

@dataclass(slots=True)
class TelemetryFrame:
    """
    Memory-isolated flat telemetry data layout utilizing __slots__ to enforce 
    O(1) lookups and eliminate overhead from dynamic allocations inside the 120Hz loop.
    """
    frame_index: int
    timestamp_ns: int
    
    # HMD Spatial & Kinematic Telemetry
    hmd_pos_x: float; hmd_pos_y: float; hmd_pos_z: float
    hmd_rot_x: float; hmd_rot_y: float; hmd_rot_z: float; hmd_rot_w: float
    hmd_tracking_valid: float
    
    # Left Controller Telemetry
    left_pos_x: float; left_pos_y: float; left_pos_z: float
    left_rot_x: float; left_rot_y: float; left_rot_z: float; left_rot_w: float
    left_trigger: float; left_grip: float; left_joy_x: float; left_joy_y: float
    left_tracking_valid: float
    
    # Right Controller Telemetry
    right_pos_x: float; right_pos_y: float; right_pos_z: float
    right_rot_x: float; right_rot_y: float; right_rot_z: float; right_rot_w: float
    right_trigger: float; right_grip: float; right_joy_x: float; right_joy_y: float
    right_tracking_valid: float
    
    # Unified Eye Tracking Telemetry
    left_eye_pos_x: float; left_eye_pos_y: float; left_eye_pos_z: float
    left_eye_rot_x: float; left_eye_rot_y: float; left_eye_rot_z: float; left_eye_rot_w: float
    right_eye_pos_x: float; right_eye_pos_y: float; right_eye_pos_z: float
    right_eye_rot_x: float; right_eye_rot_y: float; right_eye_rot_z: float; right_eye_rot_w: float
    eye_tracking_valid: float

    # Biometrics & Environment Telemetry
    left_pupil_size: float; right_pupil_size: float; heart_rate_bpm: float
    distance_to_boundary: float; app_fps: float; event_marker: float
    battery_hmd: float; battery_left: float; battery_right: float
    haptic_left_intensity: float; haptic_right_intensity: float
    gaze_focal_distance: float; voice_amplitude_db: float
    cpu_utilization: float; gpu_utilization: float

    # Category 7: Virtuális Környezet Állapot (Added to fulfill specification sheet)
    scene_id: float
    target_obj_pos_x: float; target_obj_pos_y: float; target_obj_pos_z: float
    dist_to_target_left: float; dist_to_target_right: float

    def to_tuple(self) -> tuple:
        """Converts internal parameters into a flat scalar tuple matching PyArrow memory tables."""
        return (
            self.frame_index, self.timestamp_ns,
            
            # 1. HMD Kinematics
            self.hmd_pos_x, self.hmd_pos_y, self.hmd_pos_z,
            self.hmd_rot_x, self.hmd_rot_y, self.hmd_rot_z, self.hmd_rot_w,
            
            # 2. Left Controller
            self.left_pos_x, self.left_pos_y, self.left_pos_z,
            self.left_rot_x, self.left_rot_y, self.left_rot_z, self.left_rot_w,
            self.left_trigger, self.left_grip, self.left_joy_x, self.left_joy_y,
            
            # 3. Right Controller
            self.right_pos_x, self.right_pos_y, self.right_pos_z,
            self.right_rot_x, self.right_rot_y, self.right_rot_z, self.right_rot_w,
            self.right_trigger, self.right_grip, self.right_joy_x, self.right_joy_y,
            
            # 4. Eye Tracking Left
            self.left_eye_pos_x, self.left_eye_pos_y, self.left_eye_pos_z,
            self.left_eye_rot_x, self.left_eye_rot_y, self.left_eye_rot_z, self.left_eye_rot_w,
            
            # 5. Eye Tracking Right
            self.right_eye_pos_x, self.right_eye_pos_y, self.right_eye_pos_z,
            self.right_eye_rot_x, self.right_eye_rot_y, self.right_eye_rot_z, self.right_eye_rot_w,
            
            # 6. Validity Flags (Moved down to match schema definition exactly)
            self.hmd_tracking_valid,
            self.left_tracking_valid,
            self.right_tracking_valid,
            self.eye_tracking_valid,
            
            # 7. Biometrics
            self.left_pupil_size, self.right_pupil_size, self.heart_rate_bpm,
            
            # 8. Environment & System State
            self.distance_to_boundary, self.app_fps, self.event_marker,
            self.battery_hmd, self.battery_left, self.battery_right,
            self.haptic_left_intensity, self.haptic_right_intensity,
            self.gaze_focal_distance, self.voice_amplitude_db,
            self.cpu_utilization, self.gpu_utilization,
            
            # 9. Virtual Environment State
            self.scene_id,
            self.target_obj_pos_x, self.target_obj_pos_y, self.target_obj_pos_z,
            self.dist_to_target_left, self.dist_to_target_right
        )

    @classmethod
    def create_empty(cls, frame_idx: int) -> 'TelemetryFrame':
        """Generates a default vector to protect data sequence continuity during hardware drops."""
        return cls(
            frame_index=frame_idx, timestamp_ns=time.perf_counter_ns(),
            hmd_pos_x=0.0, hmd_pos_y=0.0, hmd_pos_z=0.0, hmd_rot_x=0.0, hmd_rot_y=0.0, hmd_rot_z=0.0, hmd_rot_w=1.0, hmd_tracking_valid=0.0,
            left_pos_x=0.0, left_pos_y=0.0, left_pos_z=0.0, left_rot_x=0.0, left_rot_y=0.0, left_rot_z=0.0, left_rot_w=1.0,
            left_trigger=0.0, left_grip=0.0, left_joy_x=0.0, left_joy_y=0.0, left_tracking_valid=0.0,
            right_pos_x=0.0, right_pos_y=0.0, right_pos_z=0.0, right_rot_x=0.0, right_rot_y=0.0, right_rot_z=0.0, right_rot_w=1.0,
            right_trigger=0.0, right_grip=0.0, right_joy_x=0.0, right_joy_y=0.0, right_tracking_valid=0.0,
            left_eye_pos_x=0.0, left_eye_pos_y=0.0, left_eye_pos_z=0.0, left_eye_rot_x=0.0, left_eye_rot_y=0.0, left_eye_rot_z=0.0, left_eye_rot_w=1.0,
            right_eye_pos_x=0.0, right_eye_pos_y=0.0, right_eye_pos_z=0.0, right_eye_rot_x=0.0, right_eye_rot_y=0.0, right_eye_rot_z=0.0, right_eye_rot_w=1.0,
            eye_tracking_valid=0.0, left_pupil_size=0.0, right_pupil_size=0.0, heart_rate_bpm=0.0,
            distance_to_boundary=0.0, app_fps=90.0, event_marker=0.0,
            battery_hmd=1.0, battery_left=1.0, battery_right=1.0,
            haptic_left_intensity=0.0, haptic_right_intensity=0.0,
            gaze_focal_distance=0.0, voice_amplitude_db=-60.0,
            cpu_utilization=0.0, gpu_utilization=0.0,
            scene_id=1.0, # Default to Menu state
            target_obj_pos_x=0.0, target_obj_pos_y=0.0, target_obj_pos_z=0.0,
            dist_to_target_left=0.0, dist_to_target_right=0.0
        )