# src/eye_tracking/ext_eye_gaze.py

import logging

import xr

from src.core.datatypes import TelemetryFrame
from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory

logger = logging.getLogger(__name__)


class EXTEyeGazeDriver(IEyeTrackingDriver):
    """
    Standard Khronos Biometric Driver (Priority 10).
    Leverages XR_EXT_eye_gaze_interaction. Designed to run inside an Overlay session.
    Gracefully handles SPACE_LOCATION_VALID_BIT drops caused by focus loss or blinking.
    """

    def __init__(self) -> None:
        self.session: xr.Session | None = None
        self.app_space: xr.Space | None = None

        # Published to the backend, which attaches and syncs it. See the
        # contract on IEyeTrackingDriver: this driver used to attach and sync
        # the set itself, which is why the OpenXR backend failed to bind on
        # every headset that selected this driver.
        self.gaze_action_set: xr.ActionSet | None = None
        self.eye_gaze_action: xr.Action | None = None
        self.eye_space: xr.Space | None = None

    def get_extension_name(self) -> str:
        return "XR_EXT_eye_gaze_interaction"

    def get_additional_extensions(self) -> list[str]:
        return []

    def get_priority(self) -> int:
        return 10

    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        self.session = session
        self.app_space = app_space

        try:
            self.gaze_action_set = xr.create_action_set(
                instance,
                xr.ActionSetCreateInfo(
                    action_set_name="biometric_ext_gaze_set",
                    localized_action_set_name="Biometric Gaze Tracking",
                ),
            )

            self.eye_gaze_action = xr.create_action(
                self.gaze_action_set,
                xr.ActionCreateInfo(
                    action_name="eye_gaze",
                    action_type=xr.ActionType.POSE_INPUT,
                    localized_action_name="Eye Gaze",
                ),
            )

            xr.suggest_interaction_profile_bindings(
                instance,
                xr.InteractionProfileSuggestedBinding(
                    interaction_profile=xr.string_to_path(
                        instance, "/interaction_profiles/ext/eye_gaze_interaction"
                    ),
                    suggested_bindings=[
                        xr.ActionSuggestedBinding(
                            self.eye_gaze_action,
                            xr.string_to_path(instance, "/user/eyes_ext/input/gaze_ext/pose"),
                        )
                    ],
                ),
            )

            self.eye_space = xr.create_action_space(
                self.session, xr.ActionSpaceCreateInfo(action=self.eye_gaze_action)
            )

            logger.info("XR_EXT_eye_gaze_interaction initialized successfully.")
            return True

        except xr.XrException as e:
            logger.error(f"Failed to bind EXT Eye Gaze interaction: {e}")
            return False

    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        if not self.eye_space or not self.app_space:
            return

        # No sync here. The backend syncs every attached action set once per
        # frame, before it calls this; syncing again with only *this* set would
        # mark the controller actions inactive for the rest of the frame. The
        # HTC driver has always relied on the backend's sync -- this one now
        # does too.
        try:
            eye_loc = xr.locate_space(self.eye_space, self.app_space, timestamp_ns)

            # Check BOTH position and orientation validity bits.
            # If the user blinks or the overlay loses focus, these bits will drop.
            is_valid = (eye_loc.location_flags & xr.SPACE_LOCATION_ORIENTATION_VALID_BIT) and (
                eye_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT
            )

            if is_valid:
                pos = eye_loc.pose.position
                rot = eye_loc.pose.orientation

                # XR_EXT_eye_gaze_interaction only provides a unified/cyclopean ray.
                frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z = (
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

                frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z = (
                    pos.x,
                    pos.y,
                    pos.z,
                )
                (
                    frame.right_eye_rot_x,
                    frame.right_eye_rot_y,
                    frame.right_eye_rot_z,
                    frame.right_eye_rot_w,
                ) = rot.x, rot.y, rot.z, rot.w

                frame.eye_tracking_valid = 1.0
                frame.left_pupil_size = -1.0  # Explicitly mark unsupported metrics
                frame.right_pupil_size = -1.0
            else:
                frame.eye_tracking_valid = 0.0

        except xr.XrException as e:
            # Prevent single-frame exceptions from crashing the telemetry loop
            logger.debug(f"Eye gaze pose unavailable this frame: {e}")
            frame.eye_tracking_valid = 0.0

    def shutdown(self) -> None:
        if self.eye_space:
            xr.destroy_space(self.eye_space)
        if self.gaze_action_set:
            xr.destroy_action_set(self.gaze_action_set)


EyeTrackingFactory.register_driver(EXTEyeGazeDriver)
