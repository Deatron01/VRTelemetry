import openvr
import numpy as np
from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame

class SteamVRBackend(IVRBackend):
    """
    Fallback context driver utilizing the legacy openvr runtime configuration layer.
    """
    def __init__(self):
        self.vr_system = None
        self.poses = None

    def initialize(self) -> bool:
        if not openvr.isHmdPresent():
            return False
        try:
            self.vr_system = openvr.init(openvr.VRApplication_Background)
            self.poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
            return True
        except Exception as e:
            print(f"[*] OpenVR legacy interface bypassed: {e}")
            return False

    def _convert_matrix(self, m) -> tuple:
        # Resolves position space translation mappings directly
        x, y, z = m[0][3], m[1][3], m[2][3]
        
        # Trace matrix evaluation calculation to resolve quaternion representations
        t = m[0][0] + m[1][1] + m[2][2]
        if t > 0:
            s = 0.5 / np.sqrt(t + 1.0)
            qw = 0.25 / s
            qx = (m[2][1] - m[1][2]) * s
            qy = (m[0][2] - m[2][0]) * s
            qz = (m[1][0] - m[0][1]) * s
        else:
            if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
                s = 2.0 * np.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2])
                qw = (m[2][1] - m[1][2]) / s
                qx = 0.25 * s
                qy = (m[0][1] + m[1][0]) / s
                qz = (m[0][2] + m[2][0]) / s
            elif m[1][1] > m[2][2]:
                s = 2.0 * np.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2])
                qw = (m[0][2] - m[2][0]) / s
                qx = (m[0][1] + m[1][0]) / s
                qy = 0.25 * s
                qz = (m[1][2] + m[2][1]) / s
            else:
                s = 2.0 * np.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1])
                qw = (m[1][0] - m[0][1]) / s
                qx = (m[0][2] + m[2][0]) / s
                qy = (m[1][2] + m[2][1]) / s
                qz = 0.25 * s
        return x, y, z, qx, qy, qz, qw

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.vr_system:
            return frame

        self.vr_system.getDeviceToAbsoluteTrackingPose(openvr.TrackingUniverseStanding, 0.0, self.poses)
        
        hmd_pose = self.poses[openvr.k_unTrackedDeviceIndex_Hmd]
        if hmd_pose.bPoseIsValid:
            x, y, z, qx, qy, qz, qw = self._convert_matrix(hmd_pose.mDeviceToAbsoluteTracking)
            frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = x, y, z
            frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = qx, qy, qz, qw
            frame.hmd_tracking_valid = 1.0

        for i in range(1, openvr.k_unMaxTrackedDeviceCount):
            pose = self.poses[i]
            if not pose.bPoseIsValid:
                continue
            device_class = self.vr_system.getTrackedDeviceClass(i)
            if device_class == openvr.TrackedDeviceClass_Controller:
                role = self.vr_system.getControllerRoleForTrackedDeviceIndex(i)
                cx, cy, cz, cqx, cqy, cqz, cqw = self._convert_matrix(pose.mDeviceToAbsoluteTracking)
                
                # Fetch controller scalar properties mapping layout
                _, p_state = self.vr_system.getControllerState(i)
                trigger = float(p_state.rAxis[0].x) # Standard mapping array location index for index trigger lines
                
                if role == openvr.TrackedControllerRole_LeftHand:
                    frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = cx, cy, cz
                    frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = cqx, cqy, cqz, cqw
                    frame.left_tracking_valid = 1.0
                    frame.left_trigger = trigger
                elif role == openvr.TrackedControllerRole_RightHand:
                    frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = cx, cy, cz
                    frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = cqx, cqy, cqz, cqw
                    frame.right_tracking_valid = 1.0
                    frame.right_trigger = trigger
        return frame

    def shutdown(self) -> None:
        if self.vr_system:
            openvr.shutdown()
            self.vr_system = None