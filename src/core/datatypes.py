from dataclasses import dataclass
import time

@dataclass(slots=True)
class TelemetryFrame:
    """
    A strictly defined, memory-efficient data structure for a single telemetry frame.
    Using slots=True prevents dynamic dictionary allocation, crucial for 120Hz stability.
    """
    frame_index: int
    timestamp_ns: int
    
    # HMD
    hmd_pos_x: float; hmd_pos_y: float; hmd_pos_z: float
    hmd_rot_x: float; hmd_rot_y: float; hmd_rot_z: float; hmd_rot_w: float
    hmd_tracking_valid: float
    
    # Left Controller
    left_pos_x: float; left_pos_y: float; left_pos_z: float
    left_rot_x: float; left_rot_y: float; left_rot_z: float; left_rot_w: float
    left_trigger: float; left_grip: float; left_joy_x: float; left_joy_y: float
    left_tracking_valid: float
    
    # Right Controller
    right_pos_x: float; right_pos_y: float; right_pos_z: float
    right_rot_x: float; right_rot_y: float; right_rot_z: float; right_rot_w: float
    right_trigger: float; right_grip: float; right_joy_x: float; right_joy_y: float
    right_tracking_valid: float
    
    # Eye Tracking (Defaults to 0.0 if hardware lacks support)
    left_eye_pos_x: float; left_eye_pos_y: float; left_eye_pos_z: float
    left_eye_rot_x: float; left_eye_rot_y: float; left_eye_rot_z: float; left_eye_rot_w: float
    right_eye_pos_x: float; right_eye_pos_y: float; right_eye_pos_z: float
    right_eye_rot_x: float; right_eye_rot_y: float; right_eye_rot_z: float; right_eye_rot_w: float
    eye_tracking_valid: float

    # System & Biometrics
    left_pupil_size: float; right_pupil_size: float; heart_rate_bpm: float
    cpu_utilization: float; gpu_utilization: float
    battery_hmd: float; battery_left: float; battery_right: float

    def to_tuple(self) -> tuple:
        """Converts the frame to a flat tuple for ultra-fast PyArrow/Parquet ingestion."""
        # The order here matches the AsyncParquetWriter PyArrow schema exactly.
        return (
            self.frame_index,
            self.timestamp_ns,
            
            # HMD
            self.hmd_pos_x,
            self.hmd_pos_y,
            self.hmd_pos_z,
            self.hmd_rot_x,
            self.hmd_rot_y,
            self.hmd_rot_z,
            self.hmd_rot_w,
            self.hmd_tracking_valid,
            
            # Left Controller
            self.left_pos_x,
            self.left_pos_y,
            self.left_pos_z,
            self.left_rot_x,
            self.left_rot_y,
            self.left_rot_z,
            self.left_rot_w,
            self.left_trigger,
            self.left_grip,
            self.left_joy_x,
            self.left_joy_y,
            self.left_tracking_valid,
            
            # Right Controller
            self.right_pos_x,
            self.right_pos_y,
            self.right_pos_z,
            self.right_rot_x,
            self.right_rot_y,
            self.right_rot_z,
            self.right_rot_w,
            self.right_trigger,
            self.right_grip,
            self.right_joy_x,
            self.right_joy_y,
            self.right_tracking_valid,
            
            # Eye Tracking
            self.left_eye_pos_x,
            self.left_eye_pos_y,
            self.left_eye_pos_z,
            self.left_eye_rot_x,
            self.left_eye_rot_y,
            self.left_eye_rot_z,
            self.left_eye_rot_w,
            self.right_eye_pos_x,
            self.right_eye_pos_y,
            self.right_eye_pos_z,
            self.right_eye_rot_x,
            self.right_eye_rot_y,
            self.right_eye_rot_z,
            self.right_eye_rot_w,
            self.eye_tracking_valid,
            
            # System & Biometrics
            self.left_pupil_size,
            self.right_pupil_size,
            self.heart_rate_bpm,
            self.cpu_utilization,
            self.gpu_utilization,
            self.battery_hmd,
            self.battery_left,
            self.battery_right,
        )

    @classmethod
    def create_empty(cls, frame_idx: int) -> 'TelemetryFrame':
        """Generates a safe, zeroed-out frame in case of total hardware failure."""
        return cls(
            frame_index=frame_idx, timestamp_ns=time.perf_counter_ns(),
            hmd_pos_x=0.0, hmd_pos_y=0.0, hmd_pos_z=0.0, hmd_rot_x=0.0, hmd_rot_y=0.0, hmd_rot_z=0.0, hmd_rot_w=1.0,
            hmd_tracking_valid=0.0,
            left_pos_x=0.0, left_pos_y=0.0, left_pos_z=0.0, left_rot_x=0.0, left_rot_y=0.0, left_rot_z=0.0, left_rot_w=1.0,
            left_trigger=0.0, left_grip=0.0, left_joy_x=0.0, left_joy_y=0.0, left_tracking_valid=0.0,
            right_pos_x=0.0, right_pos_y=0.0, right_pos_z=0.0, right_rot_x=0.0, right_rot_y=0.0, right_rot_z=0.0, right_rot_w=1.0,
            right_trigger=0.0, right_grip=0.0, right_joy_x=0.0, right_joy_y=0.0, right_tracking_valid=0.0,
            left_eye_pos_x=0.0, left_eye_pos_y=0.0, left_eye_pos_z=0.0, left_eye_rot_x=0.0, left_eye_rot_y=0.0, left_eye_rot_z=0.0, left_eye_rot_w=1.0,
            right_eye_pos_x=0.0, right_eye_pos_y=0.0, right_eye_pos_z=0.0, right_eye_rot_x=0.0, right_eye_rot_y=0.0, right_eye_rot_z=0.0, right_eye_rot_w=1.0,
            eye_tracking_valid=0.0,
            left_pupil_size=0.0, right_pupil_size=0.0, heart_rate_bpm=0.0,
            cpu_utilization=0.0, gpu_utilization=0.0,
            battery_hmd=1.0, battery_left=1.0, battery_right=1.0
        )