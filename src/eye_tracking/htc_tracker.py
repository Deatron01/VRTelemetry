# src/eye_tracking/htc_tracker.py

import logging
import ctypes
import xr
from typing import List, Optional

from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory
from src.core.datatypes import TelemetryFrame

logger = logging.getLogger(__name__)

class HTCEyeTrackingDriver(IEyeTrackingDriver):
    def __init__(self) -> None:
        self.instance: Optional[xr.Instance] = None
        self.session: Optional[xr.Session] = None
        self.app_space: Optional[xr.Space] = None
        self.facial_tracker = None
        
        self._xrCreateFacialTrackerHTC = None
        self._xrGetFacialExpressionsHTC = None
        
        # Action handles for standard gaze vectors
        self.gaze_action_set: Optional[xr.ActionSet] = None
        self.gaze_pose_action: Optional[xr.Action] = None
        self.gaze_space: Optional[xr.Space] = None

    def get_extension_name(self) -> str:
        return "XR_HTC_facial_tracking"

    def get_additional_extensions(self) -> List[str]:
        # Require standard eye gaze interaction to get spatial vectors
        return ["XR_EXT_eye_gaze_interaction"]

    def get_priority(self) -> int:
        return 50

    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        self.instance = instance
        self.session = session
        self.app_space = app_space
        
        try:
            # 1. Initialize HTC Facial Tracker (for blinks/pupil)
            self._xrCreateFacialTrackerHTC = xr.get_instance_proc_addr(self.instance, "xrCreateFacialTrackerHTC")
            self._xrGetFacialExpressionsHTC = xr.get_instance_proc_addr(self.instance, "xrGetFacialExpressionsHTC")

            if self._xrCreateFacialTrackerHTC:
                create_info = xr.FacialTrackerCreateInfoHTC(facial_tracking_type=xr.FacialTrackingTypeHTC.EYE_DEFAULT)
                self.facial_tracker = ctypes.c_void_p()
                func = ctypes.CFUNCTYPE(xr.Result, xr.Session, ctypes.POINTER(xr.FacialTrackerCreateInfoHTC), ctypes.POINTER(ctypes.c_void_p))(self._xrCreateFacialTrackerHTC)
                func(self.session, ctypes.byref(create_info), ctypes.byref(self.facial_tracker))
            
            # 2. Initialize Standard Gaze Interaction (for X/Y/Z vectors)
            self.gaze_action_set = xr.create_action_set(
                self.instance, xr.ActionSetCreateInfo(action_set_name="gaze_set", localized_action_set_name="Gaze Set")
            )
            self.gaze_pose_action = xr.create_action(
                self.gaze_action_set, xr.ActionCreateInfo(action_name="eye_gaze", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Eye Gaze")
            )
            
            xr.suggest_interaction_profile_bindings(
                self.instance,
                xr.InteractionProfileSuggestedBinding(
                    interaction_profile=xr.string_to_path(self.instance, "/interaction_profiles/ext/eye_gaze_interaction"),
                    suggested_bindings=[
                        xr.ActionSuggestedBinding(self.gaze_pose_action, xr.string_to_path(self.instance, "/user/eyes_ext/input/gaze_ext/pose")),
                    ]
                )
            )
            
            self.gaze_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.gaze_pose_action))
            
            # NOTE: We do NOT attach action sets here anymore. 
            # The backend aggregates and registers them safely in a single call.
            
            logger.info("HTC Facial and Eye Gaze Trackers explicitly initialized.")
            return True
            
        except Exception as e:
            logger.error(f"HTC Eye Tracker init failed: {e}")
            return False

    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        frame.eye_tracking_valid = 0.0

        # 1. Harvest Blendshapes (Blinks/Pupil via HTC extension)
        if self.facial_tracker:
            try:
                expressions = xr.FacialExpressionsHTC()
                func = ctypes.CFUNCTYPE(xr.Result, ctypes.c_void_p, ctypes.POINTER(xr.FacialExpressionsHTC))(self._xrGetFacialExpressionsHTC)
                res = func(self.facial_tracker, ctypes.byref(expressions))

                if res == xr.Result.SUCCESS and expressions.is_active:
                    frame.left_pupil_size = 1.0 - expressions.expression_weightings[xr.FacialExpressionHTC.EYE_CLOSED_LEFT]
                    frame.right_pupil_size = 1.0 - expressions.expression_weightings[xr.FacialExpressionHTC.EYE_CLOSED_RIGHT]
                    frame.eye_tracking_valid = 1.0
            except Exception as e:
                logger.debug(f"HTC Facial fault: {e}")

        # 2. Harvest Spatial Vectors (Where the user is looking)
        if self.gaze_space and self.gaze_action_set:
            try:
                gaze_loc = xr.locate_space(self.gaze_space, self.app_space, timestamp_ns)
                if gaze_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                    pos = gaze_loc.pose.position
                    rot = gaze_loc.pose.orientation
                    frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z = pos.x, pos.y, pos.z
                    frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z = pos.x, pos.y, pos.z
                    frame.eye_tracking_valid = 1.0
            except Exception as e:
                logger.debug(f"Eye Gaze spatial fault: {e}")

    def shutdown(self) -> None:
        if self.facial_tracker and self.instance:
            destroy = xr.get_instance_proc_addr(self.instance, "xrDestroyFacialTrackerHTC")
            if destroy:
                ctypes.CFUNCTYPE(xr.Result, ctypes.c_void_p)(destroy)(self.facial_tracker)
        if self.gaze_space: xr.destroy_space(self.gaze_space)
        if self.gaze_action_set: xr.destroy_action_set(self.gaze_action_set)

EyeTrackingFactory.register_driver(HTCEyeTrackingDriver)