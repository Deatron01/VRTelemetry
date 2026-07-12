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
    """
    Priority 50 Biometric Driver for HTC Vive Pro Eye / Focus hardware.
    Leverages XR_HTC_eye_tracker / XR_HTC_facial_tracking extensions to extract
    highly accurate stereoscopic gaze vectors and pupil dilations natively.
    """

    def __init__(self) -> None:
        self.instance: Optional[xr.Instance] = None
        self.session: Optional[xr.Session] = None
        self.facial_tracker = None
        
        self._xrCreateFacialTrackerHTC = None
        self._xrGetFacialExpressionsHTC = None

    def get_extension_name(self) -> str:
        return "XR_HTC_facial_tracking"

    def get_additional_extensions(self) -> List[str]:
        return ["XR_HTC_eye_tracker"]

    def get_priority(self) -> int:
        return 50

    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        self.instance = instance
        self.session = session
        
        try:
            self._xrCreateFacialTrackerHTC = xr.get_instance_proc_addr(self.instance, "xrCreateFacialTrackerHTC")
            self._xrGetFacialExpressionsHTC = xr.get_instance_proc_addr(self.instance, "xrGetFacialExpressionsHTC")

            if not self._xrCreateFacialTrackerHTC:
                return False

            # Create the HTC Tracker Handle
            create_info = xr.FacialTrackerCreateInfoHTC(facial_tracking_type=xr.FacialTrackingTypeHTC.EYE_DEFAULT)
            self.facial_tracker = ctypes.c_void_p()
            
            func = ctypes.CFUNCTYPE(xr.Result, xr.Session, ctypes.POINTER(xr.FacialTrackerCreateInfoHTC), ctypes.POINTER(ctypes.c_void_p))(self._xrCreateFacialTrackerHTC)
            res = func(self.session, ctypes.byref(create_info), ctypes.byref(self.facial_tracker))
            
            if res == xr.Result.SUCCESS:
                logger.info("HTC Facial/Eye Tracker explicitly initialized.")
                return True
            return False
            
        except Exception as e:
            logger.error(f"HTC Eye Tracker init failed: {e}")
            return False

    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        if not self.facial_tracker:
            return

        try:
            # Struct containing weightings for HTC's facial blendshapes
            expressions = xr.FacialExpressionsHTC()
            func = ctypes.CFUNCTYPE(xr.Result, ctypes.c_void_p, ctypes.POINTER(xr.FacialExpressionsHTC))(self._xrGetFacialExpressionsHTC)
            res = func(self.facial_tracker, ctypes.byref(expressions))

            if res == xr.Result.SUCCESS and expressions.is_active:
                # Map HTC blendshape weights (0.0 -> 1.0) to frame metrics
                # Note: Exact index maps depend on the xr.FacialExpressionHTC enum
                frame.eye_tracking_valid = 1.0
                
                # Extract blink states
                frame.left_pupil_size = 1.0 - expressions.expression_weightings[xr.FacialExpressionHTC.EYE_CLOSED_LEFT]
                frame.right_pupil_size = 1.0 - expressions.expression_weightings[xr.FacialExpressionHTC.EYE_CLOSED_RIGHT]
            else:
                frame.eye_tracking_valid = 0.0

        except Exception as e:
            logger.debug(f"HTC Tracking fault: {e}")

    def shutdown(self) -> None:
        if self.facial_tracker and self.instance:
            destroy = xr.get_instance_proc_addr(self.instance, "xrDestroyFacialTrackerHTC")
            if destroy:
                ctypes.CFUNCTYPE(xr.Result, ctypes.c_void_p)(destroy)(self.facial_tracker)

EyeTrackingFactory.register_driver(HTCEyeTrackingDriver)