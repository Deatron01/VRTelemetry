# src/backends/backend_steamvr.py

import logging
import math
import time

import openvr

from src.backends.tracking_faults import TrackingFaultLog
from src.core.datatypes import TelemetryFrame
from src.core.interfaces import IVRBackend

logger = logging.getLogger(__name__)

#: What a failed OpenVR read is allowed to look like (VRT-13). ``OpenVRError``
#: is the base of every error pyopenvr raises for a property or a device --
#: ``TrackedPropertyError`` and friends all derive from it. ``ValueError`` and
#: ``OSError`` cover the ctypes boundary underneath.
#:
#: What is deliberately *not* in this tuple is ``TypeError``, and narrowing it
#: out is what exposed the bug fixed in this commit: pyopenvr dropped the
#: trailing ``error`` out-parameter from ``get*TrackedDeviceProperty`` after
#: 1.x, so every call in this file passed one argument too many and raised
#: ``TypeError`` on every frame. A blanket ``except Exception`` recorded that as
#: "battery unavailable", set -1.0, and did it 120 times a second for the life
#: of every SteamVR session. Nothing in the data or the log distinguished it
#: from a headset that genuinely does not report a battery.
_PROPERTY_FAULTS = (openvr.OpenVRError, ValueError, OSError)


def matrix_to_quaternion(m: list) -> tuple[float, float, float, float]:
    """
    Converts an OpenVR 3x4 transformation matrix into a normalized Quaternion.
    Returns: (x, y, z, w)
    """
    trace = m[0][0] + m[1][1] + m[2][2]

    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif (m[0][0] > m[1][1]) and (m[0][0] > m[2][2]):
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s

    return x, y, z, w


class SteamVROverlayBackend(IVRBackend):
    """
    Native OpenVR Backend Fallback.
    Explicitly initializes as an OpenVR Overlay. This bypasses OpenXR Action System
    focus requirements completely, guaranteeing pose and biometric telemetry extraction
    on SteamVR-native headsets (Valve Index, Vive Pro Eye, Bigscreen Beyond).
    """

    def __init__(self):
        self.vr_system: openvr.IVRSystem | None = None
        self.vr_overlay: openvr.IVROverlay | None = None
        self.overlay_handle = openvr.k_ulOverlayHandleInvalid
        self.vr_chaperone: openvr.IVRChaperone | None = None

        #: Per-source tracking faults (VRT-13). See
        #: :mod:`src.backends.tracking_faults`.
        self.faults = TrackingFaultLog("SteamVROverlayBackend")
        self._frames_polled = 0

        #: Cached answer to "can this HMD do eye gaze?" -- a device capability,
        #: so it is asked once per session and reused. ``None`` until asked.
        self._gaze_support: bool | None = None

    def initialize(self) -> bool:
        try:
            if not openvr.isHmdPresent():
                logger.warning("SteamVR runtime not detected.")
                return False

            self.vr_system = openvr.init(openvr.VRApplication_Overlay)
            self.vr_overlay = openvr.IVROverlay()

            self.overlay_handle = self.vr_overlay.createOverlay(
                "vrtelemetry.background.overlay", "VRTelemetry Biometric Collector"
            )

            self.vr_overlay.hideOverlay(self.overlay_handle)
            logger.info("Native OpenVR Overlay Context established successfully.")
            return True

        except openvr.OpenVRError as e:
            logger.error(f"Failed to initialize OpenVR Overlay: {e}")
            self.shutdown()
            return False

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        self._frames_polled += 1
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.vr_system:
            return frame

        try:
            poses = self.vr_system.getDeviceToAbsoluteTrackingPose(
                openvr.TrackingUniverseStanding, 0, openvr.k_unMaxTrackedDeviceCount
            )

            # --- 1. Process HMD Telemetry ---
            hmd_pose = poses[openvr.k_unTrackedDeviceIndex_Hmd]
            if hmd_pose.bPoseIsValid:
                matrix = hmd_pose.mDeviceToAbsoluteTracking
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = (
                    matrix[0][3],
                    matrix[1][3],
                    matrix[2][3],
                )
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = (
                    matrix_to_quaternion(matrix)
                )
                frame.hmd_tracking_valid = 1.0

            # --- 1b. HMD Battery ---
            try:
                frame.battery_hmd = self.vr_system.getFloatTrackedDeviceProperty(
                    openvr.k_unTrackedDeviceIndex_Hmd,
                    openvr.Prop_DeviceBatteryPercentage_Float,
                )
            except _PROPERTY_FAULTS as batt_err:
                # A tethered headset has no battery to report, which is the
                # ordinary case rather than a fault -- but it is now counted, so
                # "this hardware has no battery" and "we stopped being able to
                # read one partway through" are no longer the same log line.
                self.faults.record("hmd_battery", batt_err)
                frame.battery_hmd = -1.0

            # --- 1c. Distance to Play-Area Boundary (Chaperone) ---
            try:
                if self.vr_chaperone is None:
                    self.vr_chaperone = openvr.IVRChaperone()

                chap_ok, play_width, play_depth = self.vr_chaperone.getPlayAreaSize()
                if chap_ok and hmd_pose.bPoseIsValid:
                    half_w, half_d = play_width / 2.0, play_depth / 2.0
                    dx = half_w - abs(frame.hmd_pos_x)
                    dz = half_d - abs(frame.hmd_pos_z)
                    # Distance to the nearest wall along either axis; clamp to zero if already outside it
                    frame.distance_to_boundary = max(0.0, min(dx, dz))
                else:
                    frame.distance_to_boundary = -1.0
            except _PROPERTY_FAULTS as chap_err:
                self.faults.record("chaperone", chap_err)
                frame.distance_to_boundary = -1.0

            # --- 2. Process Controller Telemetry ---
            left_idx = self.vr_system.getTrackedDeviceIndexForControllerRole(
                openvr.TrackedControllerRole_LeftHand
            )
            right_idx = self.vr_system.getTrackedDeviceIndexForControllerRole(
                openvr.TrackedControllerRole_RightHand
            )

            # Left Controller
            if left_idx != openvr.k_unTrackedDeviceIndexInvalid:
                left_pose = poses[left_idx]
                if left_pose.bPoseIsValid:
                    m = left_pose.mDeviceToAbsoluteTracking
                    frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = m[0][3], m[1][3], m[2][3]
                    frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = (
                        matrix_to_quaternion(m)
                    )
                    frame.left_tracking_valid = 1.0

                    result, state = self.vr_system.getControllerState(left_idx)
                    if result:
                        frame.left_joy_x = state.rAxis[0].x
                        frame.left_joy_y = state.rAxis[0].y
                        frame.left_trigger = state.rAxis[1].x
                        # Grip button is bit 2 in the ulButtonPressed mask
                        frame.left_grip = (
                            1.0 if (state.ulButtonPressed & (1 << openvr.k_EButton_Grip)) else 0.0
                        )

                # Left Controller Battery
                try:
                    frame.battery_left = self.vr_system.getFloatTrackedDeviceProperty(
                        left_idx, openvr.Prop_DeviceBatteryPercentage_Float
                    )
                except _PROPERTY_FAULTS as batt_err:
                    self.faults.record("left_battery", batt_err)
                    frame.battery_left = -1.0

            # Right Controller
            if right_idx != openvr.k_unTrackedDeviceIndexInvalid:
                right_pose = poses[right_idx]
                if right_pose.bPoseIsValid:
                    m = right_pose.mDeviceToAbsoluteTracking
                    frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = (
                        m[0][3],
                        m[1][3],
                        m[2][3],
                    )
                    frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = (
                        matrix_to_quaternion(m)
                    )
                    frame.right_tracking_valid = 1.0

                    result, state = self.vr_system.getControllerState(right_idx)
                    if result:
                        frame.right_joy_x = state.rAxis[0].x
                        frame.right_joy_y = state.rAxis[0].y
                        frame.right_trigger = state.rAxis[1].x
                        frame.right_grip = (
                            1.0 if (state.ulButtonPressed & (1 << openvr.k_EButton_Grip)) else 0.0
                        )

                # Right Controller Battery
                try:
                    frame.battery_right = self.vr_system.getFloatTrackedDeviceProperty(
                        right_idx, openvr.Prop_DeviceBatteryPercentage_Float
                    )
                except _PROPERTY_FAULTS as batt_err:
                    self.faults.record("right_battery", batt_err)
                    frame.battery_right = -1.0

            # --- 3. Process General Flags & Timestamps ---
            # Prop_HasCamera_Bool reports whether the HMD has a passthrough
            # camera -- unrelated to eye tracking, and not a property every
            # runtime recognises for every device, which is why this used to
            # fail every frame with TrackedProp_UnknownProperty and permanently
            # zero out eye_tracking_valid. Prop_SupportsXrEyeGazeInteraction_Bool
            # is the actual gaze-support capability flag (added in pyopenvr
            # 2.12; see the "openvr" pin in pyproject.toml).
            #
            # Asked once per session, not once per frame. Whether a headset
            # supports gaze is a device capability: it cannot change while the
            # session is open, so re-asking at the sampling rate buys nothing.
            # On a runtime that does not recognise the property it cost one
            # fault per frame -- 4671 of them in a single 43-second session on
            # 12 Sep, at 100% of frames -- which drowns the fault summary that
            # is supposed to tell a researcher which source actually failed.
            if self._gaze_support is None:
                try:
                    self._gaze_support = bool(
                        self.vr_system.getBoolTrackedDeviceProperty(
                            openvr.k_unTrackedDeviceIndex_Hmd,
                            openvr.Prop_SupportsXrEyeGazeInteraction_Bool,
                        )
                    )
                except _PROPERTY_FAULTS as prop_err:
                    # A runtime that refuses the property has not told us the
                    # headset lacks gaze support, only that it will not answer.
                    # Recorded once, under the same source name, and the column
                    # reads 0 for the session rather than flapping.
                    self.faults.record("eye_support_probe", prop_err)
                    self._gaze_support = False
            frame.eye_tracking_valid = 1.0 if self._gaze_support else 0.0

            frame.timestamp_ns = time.perf_counter_ns()

        except (openvr.OpenVRError, ValueError, OSError, IndexError) as e:
            # Whole-frame fault: pose enumeration failed, so nothing in this
            # frame is populated. IndexError is included because the pose array
            # is indexed by device id and a device that disconnects between the
            # enumeration and the read shortens it.
            self.faults.record("frame", e)

        return frame

    def shutdown(self) -> None:
        if self.vr_overlay and self.overlay_handle != openvr.k_ulOverlayHandleInvalid:
            self.vr_overlay.destroyOverlay(self.overlay_handle)

        if self.vr_system:
            openvr.shutdown()
            self.vr_system = None

        self.faults.summarise(self._frames_polled)
        logger.info("OpenVR Overlay Context Terminated.")

    def get_refresh_rate_hz(self) -> float | None:
        if not self.vr_system:
            return None
        try:
            rate = self.vr_system.getFloatTrackedDeviceProperty(
                openvr.k_unTrackedDeviceIndex_Hmd, openvr.Prop_DisplayFrequency_Float
            )
            return float(rate) if rate and rate > 0 else None
        except _PROPERTY_FAULTS as e:
            # Logged at WARNING, not debug: the caller falls back to a
            # configured sampling cap, so a session recorded at the wrong rate
            # is the consequence, and that is worth a line someone will see.
            logger.warning(f"HMD refresh rate unavailable, using the configured cap: {e}")
            return None
