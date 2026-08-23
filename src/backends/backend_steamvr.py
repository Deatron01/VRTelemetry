# src/backends/backend_steamvr.py

import time
import math
import logging
import openvr
from typing import Optional, Tuple

from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame

logger = logging.getLogger(__name__)

def matrix_to_quaternion(m: list) -> Tuple[float, float, float, float]:
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
        self.vr_system: Optional[openvr.IVRSystem] = None
        self.vr_overlay: Optional[openvr.IVROverlay] = None
        self.overlay_handle = openvr.k_ulOverlayHandleInvalid
        
    def initialize(self) -> bool:
        try:
            if not openvr.isHmdPresent():
                logger.warning("SteamVR runtime not detected.")
                return False
                
            self.vr_system = openvr.init(openvr.VRApplication_Overlay)
            self.vr_overlay = openvr.IVROverlay()
            
            self.overlay_handle = self.vr_overlay.createOverlay(
                "vrtelemetry.background.overlay", 
                "VRTelemetry Biometric Collector"
            )
            
            self.vr_overlay.hideOverlay(self.overlay_handle)
            logger.info("Native OpenVR Overlay Context established successfully.")
            return True
            
        except openvr.OpenVRError as e:
            logger.error(f"Failed to initialize OpenVR Overlay: {e}")
            self.shutdown()
            return False

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.vr_system:
            return frame

        try:
            poses = self.vr_system.getDeviceToAbsoluteTrackingPose(
                openvr.TrackingUniverseStanding, 
                0,
                openvr.k_unMaxTrackedDeviceCount
            )
            
            # --- 1. Process HMD Telemetry ---
            hmd_pose = poses[openvr.k_unTrackedDeviceIndex_Hmd]
            if hmd_pose.bPoseIsValid:
                matrix = hmd_pose.mDeviceToAbsoluteTracking
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = matrix[0][3], matrix[1][3], matrix[2][3]
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = matrix_to_quaternion(matrix)
                frame.hmd_tracking_valid = 1.0

            # --- 2. Process Controller Telemetry ---
            left_idx = self.vr_system.getTrackedDeviceIndexForControllerRole(openvr.TrackedControllerRole_LeftHand)
            right_idx = self.vr_system.getTrackedDeviceIndexForControllerRole(openvr.TrackedControllerRole_RightHand)

            # Left Controller
            if left_idx != openvr.k_unTrackedDeviceIndexInvalid:
                left_pose = poses[left_idx]
                if left_pose.bPoseIsValid:
                    m = left_pose.mDeviceToAbsoluteTracking
                    frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = m[0][3], m[1][3], m[2][3]
                    frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = matrix_to_quaternion(m)
                    frame.left_tracking_valid = 1.0
                    
                    result, state = self.vr_system.getControllerState(left_idx)
                    if result:
                        frame.left_joy_x = state.rAxis[0].x
                        frame.left_joy_y = state.rAxis[0].y
                        frame.left_trigger = state.rAxis[1].x
                        # Grip button is bit 2 in the ulButtonPressed mask
                        frame.left_grip = 1.0 if (state.ulButtonPressed & (1 << openvr.k_EButton_Grip)) else 0.0

            # Right Controller
            if right_idx != openvr.k_unTrackedDeviceIndexInvalid:
                right_pose = poses[right_idx]
                if right_pose.bPoseIsValid:
                    m = right_pose.mDeviceToAbsoluteTracking
                    frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = m[0][3], m[1][3], m[2][3]
                    frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = matrix_to_quaternion(m)
                    frame.right_tracking_valid = 1.0
                    
                    result, state = self.vr_system.getControllerState(right_idx)
                    if result:
                        frame.right_joy_x = state.rAxis[0].x
                        frame.right_joy_y = state.rAxis[0].y
                        frame.right_trigger = state.rAxis[1].x
                        frame.right_grip = 1.0 if (state.ulButtonPressed & (1 << openvr.k_EButton_Grip)) else 0.0

            # --- 3. Process General Flags & Timestamps ---
            try:
                error = openvr.TrackedPropertyError()
                gaze_support = self.vr_system.getBoolTrackedDeviceProperty(
                    openvr.k_unTrackedDeviceIndex_Hmd, 
                    openvr.Prop_HasCamera_Bool, 
                    error
                )
                frame.eye_tracking_valid = 1.0 if gaze_support else 0.0
            except Exception as prop_err:
                logger.debug(f"OpenVR Property Error: {prop_err}")
                frame.eye_tracking_valid = 0.0

            frame.timestamp_ns = time.perf_counter_ns()
            
        except Exception as e:
            logger.debug(f"OpenVR Sync Exception: {e}")

        return frame

    def shutdown(self) -> None:
        if self.vr_overlay and self.overlay_handle != openvr.k_ulOverlayHandleInvalid:
            self.vr_overlay.destroyOverlay(self.overlay_handle)
            
        if self.vr_system:
            openvr.shutdown()
            self.vr_system = None
            
        logger.info("OpenVR Overlay Context Terminated.")