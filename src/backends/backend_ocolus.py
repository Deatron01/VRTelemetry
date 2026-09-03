from src.backends.tracking_faults import TrackingFaultLog
from src.core.datatypes import TelemetryFrame
from src.core.interfaces import IVRBackend
from src.utils.logger import logger

# Every handler in this file is broad, and each one carries a `noqa` naming the
# reason rather than the file carrying a blanket exemption (VRT-13). The reason
# is the same in all three places and is stated once here:
#
# LibOVR is reached through the optional `ovr` binding, which publishes no
# exception base class of its own -- failures surface as whatever the ctypes
# layer beneath it raised. There is no narrower tuple to write that would not
# be a guess, and a guess here fails in the direction that ends a recording.
#
# What keeps this honest is that nothing is discarded: initialize() reports the
# failure by returning False, poll_frame() attributes it to a named source in
# `self.faults` so it appears in the shutdown summary, and shutdown() logs at
# ERROR. This is the tolerant side of the rule in src/core/exceptions.py -- an
# optional backend on hardware nobody in this study may own.

# Conditional import for Oculus bindings (e.g., using the pyovr wrapper)
try:
    import ovr

    OVR_AVAILABLE = True
except ImportError:
    OVR_AVAILABLE = False


class OculusBackend(IVRBackend):
    """
    Native LibOVR fallback backend.
    Provides direct access to Oculus runtime telemetry when OpenXR is undesirable.
    """

    def __init__(self):
        self.session = None
        self.luid = None
        self.hmd_desc = None
        self.has_eye_tracking = False  # LibOVR standard SDK does not route eye tracking directly

        #: Per-source tracking faults (VRT-13). See
        #: :mod:`src.backends.tracking_faults`.
        self.faults = TrackingFaultLog("OculusBackend")
        self._frames_polled = 0

    def initialize(self) -> bool:
        if not OVR_AVAILABLE:
            logger.warning(
                "LibOVR Python bindings (ovr) not installed. Oculus backend unavailable."
            )
            return False

        try:
            ovr.initialize(None)
            self.session, self.luid = ovr.create()
            self.hmd_desc = ovr.getHmdDesc(self.session)
            logger.info(f"Oculus Native Backend Initialized: {self.hmd_desc.ProductName}")
            return True
        except Exception as e:  # noqa: BLE001 - see the module note: `ovr` has no exception base
            logger.error(f"Oculus Backend Initialization failed: {e}", exc_info=True)
            self.shutdown()
            return False

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        self._frames_polled += 1
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.session:
            return frame

        try:
            # Query the tracking state looking 0 seconds ahead (absolute present)
            display_time = ovr.getPredictedDisplayTime(self.session, 0)
            tracking_state = ovr.getTrackingState(self.session, display_time, True)

            # 1. HMD Pose Extraction
            head_pose = tracking_state.HeadPose.ThePose
            if tracking_state.StatusFlags & ovr.Status_PositionTracked:
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = (
                    head_pose.Position.x,
                    head_pose.Position.y,
                    head_pose.Position.z,
                )
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = (
                    head_pose.Orientation.x,
                    head_pose.Orientation.y,
                    head_pose.Orientation.z,
                    head_pose.Orientation.w,
                )
                frame.hmd_tracking_valid = 1.0

            # 2. Controller Pose Extraction
            # LibOVR treats hands as an array index [0 = Left, 1 = Right]
            hand_poses = tracking_state.HandPoses
            hand_status = tracking_state.HandStatusFlags

            # Left Hand
            if hand_status[0] & ovr.Status_PositionTracked:
                frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = (
                    hand_poses[0].ThePose.Position.x,
                    hand_poses[0].ThePose.Position.y,
                    hand_poses[0].ThePose.Position.z,
                )
                frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = (
                    hand_poses[0].ThePose.Orientation.x,
                    hand_poses[0].ThePose.Orientation.y,
                    hand_poses[0].ThePose.Orientation.z,
                    hand_poses[0].ThePose.Orientation.w,
                )
                frame.left_tracking_valid = 1.0

            # Right Hand
            if hand_status[1] & ovr.Status_PositionTracked:
                frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = (
                    hand_poses[1].ThePose.Position.x,
                    hand_poses[1].ThePose.Position.y,
                    hand_poses[1].ThePose.Position.z,
                )
                frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = (
                    hand_poses[1].ThePose.Orientation.x,
                    hand_poses[1].ThePose.Orientation.y,
                    hand_poses[1].ThePose.Orientation.z,
                    hand_poses[1].ThePose.Orientation.w,
                )
                frame.right_tracking_valid = 1.0

            # 3. Input State (Triggers)
            input_state = ovr.getInputState(self.session, ovr.ControllerType_Touch)
            frame.left_trigger = input_state.IndexTrigger[0]
            frame.right_trigger = input_state.IndexTrigger[1]
            frame.left_grip = input_state.HandTrigger[0]
            frame.right_grip = input_state.HandTrigger[1]

        except Exception as e:  # noqa: BLE001 - see the module note: `ovr` has no exception base
            # Falls back to the 0.0 defaults from create_empty(), which are
            # indistinguishable from hardware that is simply not being worn --
            # hence the tally, which is reported at shutdown.
            self.faults.record("frame", e)

        return frame

    def shutdown(self) -> None:
        if self.session:
            try:
                ovr.destroy(self.session)
                ovr.shutdown()
            except Exception as e:  # noqa: BLE001 - see the module note: `ovr` has no exception base
                logger.error(f"Error shutting down Oculus session: {e}", exc_info=True)
            finally:
                self.session = None
        self.faults.summarise(self._frames_polled)
