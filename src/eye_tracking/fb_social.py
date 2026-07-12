# src/eye_tracking/fb_social.py

import logging
import ctypes
import xr
from typing import List, Optional

from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory
from src.core.datatypes import TelemetryFrame

logger = logging.getLogger(__name__)

class FBEyeTrackingSocialDriver(IEyeTrackingDriver):
    """
    Priority 100 Biometric Driver for Meta Quest Pro hardware.
    Utilizes direct FB extension function pointers to query individual left/right
    gaze vectors and confidence values, which is resilient against action-space focus loss.
    """

    def __init__(self) -> None:
        self.instance: Optional[xr.Instance] = None
        self.session: Optional[xr.Session] = None
        self.app_space: Optional[xr.Space] = None
        self.eye_tracker = None

        self._xrCreateEyeTrackerFB = None
        self._xrGetEyeGazesFB = None

    def get_extension_name(self) -> str:
        return "XR_FB_eye_tracking_social"

    def get_additional_extensions(self) -> List[str]:
        return []

    def get_priority(self) -> int:
        return 100

    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        self.instance = instance
        self.session = session
        self.app_space = app_space

        try:
            # Resolve function pointers for FB extension
            self._xrCreateEyeTrackerFB = xr.get_instance_proc_addr(
                self.instance, "xrCreateEyeTrackerFB"
            )
            self._xrGetEyeGazesFB = xr.get_instance_proc_addr(
                self.instance, "xrGetEyeGazesFB"
            )

            if not self._xrCreateEyeTrackerFB or not self._xrGetEyeGazesFB:
                logger.error("XR_FB_eye_tracking_social loaded, but function pointers failed to resolve.")
                return False

            # Create tracker handle
            create_info = xr.EyeTrackerCreateInfoFB()
            self.eye_tracker = ctypes.c_void_p()
            
            # Construct ctypes wrapper call
            create_func = ctypes.CFUNCTYPE(
                xr.Result, xr.Session, ctypes.POINTER(xr.EyeTrackerCreateInfoFB), ctypes.POINTER(ctypes.c_void_p)
            )(self._xrCreateEyeTrackerFB)
            
            res = create_func(self.session, ctypes.byref(create_info), ctypes.byref(self.eye_tracker))
            
            if xr.Result(res).is_exception():
                logger.error(f"Failed to create FB Eye Tracker. Result: {res}")
                return False

            logger.info("Meta Quest Pro Biometric FB Eye Tracker successfully initialized.")
            return True

        except Exception as e:
            logger.error(f"FB Eye Tracking initialization exception: {e}")
            return False

    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        if not self.eye_tracker:
            return

        gaze_info = xr.EyeGazesInfoFB(base_space=self.app_space, time=timestamp_ns)
        gaze_state = xr.EyeGazesStateFB()

        get_func = ctypes.CFUNCTYPE(
            xr.Result, ctypes.c_void_p, ctypes.POINTER(xr.EyeGazesInfoFB), ctypes.POINTER(xr.EyeGazesStateFB)
        )(self._xrGetEyeGazesFB)

        res = get_func(self.eye_tracker, ctypes.byref(gaze_info), ctypes.byref(gaze_state))
        
        if res == xr.Result.SUCCESS:
            l_valid = gaze_state.gaze_poses[xr.EyePositionFB.LEFT].is_valid
            r_valid = gaze_state.gaze_poses[xr.EyePositionFB.RIGHT].is_valid

            if l_valid:
                l_pose = gaze_state.gaze_poses[xr.EyePositionFB.LEFT].pose
                frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z = l_pose.position.x, l_pose.position.y, l_pose.position.z
                frame.left_eye_rot_x, frame.left_eye_rot_y, frame.left_eye_rot_z, frame.left_eye_rot_w = l_pose.orientation.x, l_pose.orientation.y, l_pose.orientation.z, l_pose.orientation.w
                frame.left_pupil_size = gaze_state.gaze_confidences[xr.EyePositionFB.LEFT] # Overloading field for confidence rating
            
            if r_valid:
                r_pose = gaze_state.gaze_poses[xr.EyePositionFB.RIGHT].pose
                frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z = r_pose.position.x, r_pose.position.y, r_pose.position.z
                frame.right_eye_rot_x, frame.right_eye_rot_y, frame.right_eye_rot_z, frame.right_eye_rot_w = r_pose.orientation.x, r_pose.orientation.y, r_pose.orientation.z, r_pose.orientation.w
                frame.right_pupil_size = gaze_state.gaze_confidences[xr.EyePositionFB.RIGHT]

            frame.eye_tracking_valid = 1.0 if (l_valid and r_valid) else 0.0

    def shutdown(self) -> None:
        if self.eye_tracker and self.instance:
            destroy_func = xr.get_instance_proc_addr(self.instance, "xrDestroyEyeTrackerFB")
            if destroy_func:
                ctypes.CFUNCTYPE(xr.Result, ctypes.c_void_p)(destroy_func)(self.eye_tracker)
        self.eye_tracker = None

EyeTrackingFactory.register_driver(FBEyeTrackingSocialDriver)