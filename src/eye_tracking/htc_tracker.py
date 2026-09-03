# src/eye_tracking/htc_tracker.py

import ctypes
import logging

import xr

from src.backends.tracking_faults import TrackingFaultLog
from src.core.datatypes import TelemetryFrame
from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory

logger = logging.getLogger(__name__)

# The HTC facial-tracking entry points are resolved by name from the runtime and
# called through raw ctypes function pointers, so a failure arrives as OSError,
# ValueError, ctypes.ArgumentError or XrException depending on where in that
# chain it happened. This tuple is what "the extension did not answer" looks
# like; anything outside it is a defect in this driver and is left to travel up
# to the backend, which attributes it to the "eye" source (VRT-13).
_HTC_FAULTS = (xr.XrException, ctypes.ArgumentError, OSError, ValueError, AttributeError)


class HTCEyeTrackingDriver(IEyeTrackingDriver):
    def __init__(self) -> None:
        self.instance: xr.Instance | None = None
        self.session: xr.Session | None = None
        self.app_space: xr.Space | None = None
        self.facial_tracker = None

        self._xrCreateFacialTrackerHTC = None
        self._xrGetFacialExpressionsHTC = None

        # Action handles for standard gaze vectors
        self.gaze_action_set: xr.ActionSet | None = None
        self.gaze_pose_action: xr.Action | None = None
        self.gaze_space: xr.Space | None = None

        #: Faults per eye-tracking source (VRT-13). Eye data is the reason this
        #: study records at all, and a driver that fails silently produces
        #: `eye_tracking_valid = 0.0` -- byte-identical to a subject whose eyes
        #: the tracker simply could not see.
        self.faults = TrackingFaultLog("HTCEyeTrackingDriver")

    def get_extension_name(self) -> str:
        return "XR_HTC_facial_tracking"

    def get_additional_extensions(self) -> list[str]:
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
            self._xrCreateFacialTrackerHTC = xr.get_instance_proc_addr(
                self.instance, "xrCreateFacialTrackerHTC"
            )
            self._xrGetFacialExpressionsHTC = xr.get_instance_proc_addr(
                self.instance, "xrGetFacialExpressionsHTC"
            )

            if self._xrCreateFacialTrackerHTC:
                create_info = xr.FacialTrackerCreateInfoHTC(
                    facial_tracking_type=xr.FacialTrackingTypeHTC.EYE_DEFAULT
                )
                # OpenXR handles are 64-bit unsigned integers
                self.facial_tracker = ctypes.c_uint64()

                # Direct pointer execution
                self._xrCreateFacialTrackerHTC.restype = ctypes.c_int
                res = self._xrCreateFacialTrackerHTC(
                    self.session, ctypes.byref(create_info), ctypes.byref(self.facial_tracker)
                )

                if res != 0:
                    logger.warning(
                        f"Failed to initialize HTC Facial Tracker runtime structure. Code: {res}"
                    )

            # 2. Initialize Standard Gaze Interaction (for X/Y/Z vectors)
            self.gaze_action_set = xr.create_action_set(
                self.instance,
                xr.ActionSetCreateInfo(
                    action_set_name="gaze_set", localized_action_set_name="Gaze Set"
                ),
            )
            self.gaze_pose_action = xr.create_action(
                self.gaze_action_set,
                xr.ActionCreateInfo(
                    action_name="eye_gaze",
                    action_type=xr.ActionType.POSE_INPUT,
                    localized_action_name="Eye Gaze",
                ),
            )

            xr.suggest_interaction_profile_bindings(
                self.instance,
                xr.InteractionProfileSuggestedBinding(
                    interaction_profile=xr.string_to_path(
                        self.instance, "/interaction_profiles/ext/eye_gaze_interaction"
                    ),
                    suggested_bindings=[
                        xr.ActionSuggestedBinding(
                            self.gaze_pose_action,
                            xr.string_to_path(self.instance, "/user/eyes_ext/input/gaze_ext/pose"),
                        ),
                    ],
                ),
            )

            self.gaze_space = xr.create_action_space(
                self.session, xr.ActionSpaceCreateInfo(action=self.gaze_pose_action)
            )

            logger.info("HTC Facial and Eye Gaze Trackers explicitly initialized.")
            return True

        except _HTC_FAULTS as e:
            logger.error(f"HTC Eye Tracker init failed: {e}", exc_info=True)
            return False

    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        frame.eye_tracking_valid = 0.0

        # 1. Harvest Blendshapes (Blinks/Pupil via HTC extension)
        if self.facial_tracker and self._xrGetFacialExpressionsHTC:
            try:
                expressions = xr.FacialExpressionsHTC()
                self._xrGetFacialExpressionsHTC.restype = ctypes.c_int
                res = self._xrGetFacialExpressionsHTC(
                    self.facial_tracker, ctypes.byref(expressions)
                )

                if res == 0 and expressions.is_active:
                    frame.left_pupil_size = (
                        1.0
                        - expressions.expression_weightings[xr.FacialExpressionHTC.EYE_CLOSED_LEFT]
                    )
                    frame.right_pupil_size = (
                        1.0
                        - expressions.expression_weightings[xr.FacialExpressionHTC.EYE_CLOSED_RIGHT]
                    )
                    frame.eye_tracking_valid = 1.0
            except _HTC_FAULTS as e:
                self.faults.record("htc_blendshapes", e)

        # 2. Harvest Spatial Vectors (Where the user is looking)
        if self.gaze_space and self.gaze_action_set:
            try:
                gaze_loc = xr.locate_space(self.gaze_space, self.app_space, timestamp_ns)
                if gaze_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                    pos = gaze_loc.pose.position
                    rot = gaze_loc.pose.orientation

                    frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z = (
                        pos.x,
                        pos.y,
                        pos.z,
                    )
                    frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z = (
                        pos.x,
                        pos.y,
                        pos.z,
                    )

                    (
                        frame.left_eye_rot_x,
                        frame.left_eye_rot_y,
                        frame.left_eye_rot_z,
                        frame.left_eye_rot_w,
                    ) = rot.x, rot.y, rot.z, rot.w
                    (
                        frame.right_eye_rot_x,
                        frame.right_eye_rot_y,
                        frame.right_eye_rot_z,
                        frame.right_eye_rot_w,
                    ) = rot.x, rot.y, rot.z, rot.w

                    frame.eye_tracking_valid = 1.0
            except _HTC_FAULTS as e:
                self.faults.record("htc_gaze_pose", e)

    def shutdown(self) -> None:
        self.faults.summarise()
        if self.facial_tracker and self.instance:
            destroy = xr.get_instance_proc_addr(self.instance, "xrDestroyFacialTrackerHTC")
            if destroy:
                destroy.restype = ctypes.c_int
                destroy(self.facial_tracker)
        if self.gaze_space:
            xr.destroy_space(self.gaze_space)
        if self.gaze_action_set:
            xr.destroy_action_set(self.gaze_action_set)


EyeTrackingFactory.register_driver(HTCEyeTrackingDriver)
