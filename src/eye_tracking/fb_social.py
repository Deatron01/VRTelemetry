# src/eye_tracking/fb_social.py

import logging
import xr
from typing import List, Optional

from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory
from src.core.datatypes import TelemetryFrame

logger = logging.getLogger(__name__)

class FBEyeTrackingSocialDriver(IEyeTrackingDriver):
    """
    Meta Quest Pro Biometric Driver (Priority 20).
    Leverages the XR_FB_eye_tracking_social extension to extract high-fidelity social 
    eye-tracking parameters. Maps individual eye gaze positions and orientations, 
    estimating relative confidence score metrics.
    """

    def __init__(self) -> None:
        self.session: Optional[xr.Session] = None
        self.app_space: Optional[xr.Space] = None
        
        # Pointers for extension function hooks
        self.xrCreateEyeTrackerFB = None
        self.xrDestroyEyeTrackerFB = None
        self.xrGetEyeGazeFB = None
        
        self.eye_tracker: Optional[xr.EyeTrackerFB] = None

    def get_extension_name(self) -> str:
        return "XR_FB_eye_tracking_social"

    def get_additional_extensions(self) -> List[str]:
        return []

    def get_priority(self) -> int:
        return 20

    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        self.session = session
        self.app_space = app_space

        try:
            # Resolve extension function pointers dynamically
            self.xrCreateEyeTrackerFB = xr.get_instance_proc_addr(
                instance, "xrCreateEyeTrackerFB"
            )
            self.xrDestroyEyeTrackerFB = xr.get_instance_proc_addr(
                instance, "xrDestroyEyeTrackerFB"
            )
            self.xrGetEyeGazeFB = xr.get_instance_proc_addr(
                instance, "xrGetEyeGazeFB"
            )

            if not self.xrCreateEyeTrackerFB or not self.xrGetEyeGazeFB:
                logger.error("Failed to load function pointers for XR_FB_eye_tracking_social.")
                return False

            # Create the structural tracker handle
            create_info = xr.EyeTrackerCreateInfoFB()
            self.eye_tracker = self.xrCreateEyeTrackerFB(self.session, create_info)
            return True

        except Exception as e:
            logger.error(f"Initialization failure for XR_FB_eye_tracking_social driver: {e}")
            return False

    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        if not self.eye_tracker or not self.xrGetEyeGazeFB:
            return

        try:
            gaze_get_info = xr.EyeGazeGetInfoFB(
                base_space=self.app_space,
                time=timestamp_ns
            )
            
            gaze = xr.EyeGazeFB()
            result = self.xrGetEyeGazeFB(self.eye_tracker, gaze_get_info, gaze)
            
            if result == xr.Result.SUCCESS and gaze.is_valid:
                # Left eye mapping
                if gaze.gaze_flags & xr.EYE_GAZE_VALID_BIT_FB:
                    l_pos = gaze.left_eye_pose.position
                    l_rot = gaze.left_eye_pose.orientation
                    frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z = l_pos.x, l_pos.y, l_pos.z
                    frame.left_eye_rot_x, frame.left_eye_rot_y, frame.left_eye_rot_z, frame.left_eye_rot_w = l_rot.x, l_rot.y, l_rot.z, l_rot.w
                    
                    r_pos = gaze.right_eye_pose.position
                    r_rot = gaze.right_eye_pose.orientation
                    frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z = r_pos.x, r_pos.y, r_pos.z
                    frame.right_eye_rot_x, frame.right_eye_rot_y, frame.right_eye_rot_z, frame.right_eye_rot_w = r_rot.x, r_rot.y, r_rot.z, r_rot.w
                    
                    frame.eye_tracking_valid = 1.0
                    
                # Note: XR_FB_eye_tracking_social provides raw gaze expressions. 
                # Pupil diameters are filled dynamically via hardware or forward fill.
                frame.left_pupil_size = 0.0
                frame.right_pupil_size = 0.0

        except Exception as e:
            logger.debug(f"XR_FB_eye_tracking_social frame polling exception: {e}")

    def shutdown(self) -> None:
        if self.eye_tracker and self.xrDestroyEyeTrackerFB:
            try:
                self.xrDestroyEyeTrackerFB(self.eye_tracker)
            except Exception as e:
                logger.error(f"Error destroying FB Eye Tracker: {e}")
            self.eye_tracker = None

# Register with global capability driver factory
EyeTrackingFactory.register_driver(FBEyeTrackingSocialDriver)