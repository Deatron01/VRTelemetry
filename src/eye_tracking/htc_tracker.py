# src/eye_tracking/htc_tracker.py

import logging
import xr
from typing import List, Optional

from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory
from src.core.datatypes import TelemetryFrame

logger = logging.getLogger(__name__)

class HTCEyeGazeDriver(IEyeTrackingDriver):
    """
    HTC Vive Pro Eye / Vive XR Elite Biometric Driver (Priority 30).
    Leverages the XR_HTC_eye_tracker extension to extract full stereoscopic tracking positions,
    rotations, explicit pupil sizes, and micro-blink indicators.
    """

    def __init__(self) -> None:
        self.session: Optional[xr.Session] = None
        self.app_space: Optional[xr.Space] = None
        
        # Pointers for extension function hooks
        self.xrCreateEyeTrackerHTC = None
        self.xrDestroyEyeTrackerHTC = None
        self.xrGetEyeTrackerSystemPropertiesHTC = None
        self.xrGetEyeGazeHTC = None
        
        self.eye_tracker: Optional[xr.EyeTrackerHTC] = None

    def get_extension_name(self) -> str:
        return "XR_HTC_eye_tracker"

    def get_additional_extensions(self) -> List[str]:
        return []

    def get_priority(self) -> int:
        return 30

    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        self.session = session
        self.app_space = app_space

        try:
            # Resolve extension function pointers dynamically
            self.xrCreateEyeTrackerHTC = xr.get_instance_proc_addr(
                instance, "xrCreateEyeTrackerHTC"
            )
            self.xrDestroyEyeTrackerHTC = xr.get_instance_proc_addr(
                instance, "xrDestroyEyeTrackerHTC"
            )
            self.xrGetEyeGazeHTC = xr.get_instance_proc_addr(
                instance, "xrGetEyeGazeHTC"
            )

            if not self.xrCreateEyeTrackerHTC or not self.xrGetEyeGazeHTC:
                logger.error("Failed to load function pointers for XR_HTC_eye_tracker.")
                return False

            create_info = xr.EyeTrackerCreateInfoHTC()
            self.eye_tracker = self.xrCreateEyeTrackerHTC(self.session, create_info)
            return True

        except Exception as e:
            logger.error(f"Initialization failure for XR_HTC_eye_tracker driver: {e}")
            return False

    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        if not self.eye_tracker or not self.xrGetEyeGazeHTC:
            return

        try:
            gaze = xr.EyeGazeHTC()
            result = self.xrGetEyeGazeHTC(self.eye_tracker, timestamp_ns, gaze)
            
            if result == xr.Result.SUCCESS:
                # Map individual components safely
                # Left eye evaluation
                if gaze.left_eye_gaze_status == xr.EyeGazeStatusHTC.VALID:
                    l_pos = gaze.left_eye_gaze_pose.position
                    l_rot = gaze.left_eye_gaze_pose.orientation
                    frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z = l_pos.x, l_pos.y, l_pos.z
                    frame.left_eye_rot_x, frame.left_eye_rot_y, frame.left_eye_rot_z, frame.left_eye_rot_w = l_rot.x, l_rot.y, l_rot.z, l_rot.w
                    frame.left_pupil_size = float(gaze.left_eye_pupil_diameter_mm)
                
                # Right eye evaluation
                if gaze.right_eye_gaze_status == xr.EyeGazeStatusHTC.VALID:
                    r_pos = gaze.right_eye_gaze_pose.position
                    r_rot = gaze.right_eye_gaze_pose.orientation
                    frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z = r_pos.x, r_pos.y, r_pos.z
                    frame.right_eye_rot_x, frame.right_eye_rot_y, frame.right_eye_rot_z, frame.right_eye_rot_w = r_rot.x, r_rot.y, r_rot.z, r_rot.w
                    frame.right_pupil_size = float(gaze.right_eye_pupil_diameter_mm)

                if (gaze.left_eye_gaze_status == xr.EyeGazeStatusHTC.VALID or 
                    gaze.right_eye_gaze_status == xr.EyeGazeStatusHTC.VALID):
                    frame.eye_tracking_valid = 1.0

        except Exception as e:
            logger.debug(f"XR_HTC_eye_tracker frame polling exception: {e}")

    def shutdown(self) -> None:
        if self.eye_tracker and self.xrDestroyEyeTrackerHTC:
            try:
                self.xrDestroyEyeTrackerHTC(self.eye_tracker)
            except Exception as e:
                logger.error(f"Error destroying HTC Eye Tracker: {e}")
            self.eye_tracker = None

# Register with global capability driver factory
EyeTrackingFactory.register_driver(HTCEyeGazeDriver)