import openvr
from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame

class SteamVRBackend(IVRBackend):
    """
    Fallback backend utilizing the legacy OpenVR API.
    Used automatically if OpenXR initialization fails.
    """
    def __init__(self):
        self.vr_system = None
        self.poses = None
        self.has_eye_tracking = False # Standard OpenVR lacks native eye tracking without SRanipal

    def initialize(self) -> bool:
        if not openvr.isHmdPresent():
            return False
            
        try:
            self.vr_system = openvr.init(openvr.VRApplication_Background)
            self.poses = (openvr.TrackedDevicePose_t * openvr.k_unMaxTrackedDeviceCount)()
            return True
        except openvr.OpenVRError as e:
            print(f"[*] SteamVR Initialization failed: {e}")
            return False

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        
        if not self.vr_system:
            return frame

        # Fetch poses directly from the compositor buffer
        self.vr_system.getDeviceToAbsoluteTrackingPose(
            openvr.TrackingUniverseStanding, 
            0.0, # Predict at exactly now (0s ahead)
            self.poses
        )

        # 1. HMD Pose (Device 0 is always the HMD in OpenVR)
        hmd_pose = self.poses[openvr.k_unTrackedDeviceIndex_Hmd]
        if hmd_pose.bPoseIsValid:
            mat = hmd_pose.mDeviceToAbsoluteTracking
            # Extract Position (Column 3 of 3x4 Matrix)
            frame.hmd_pos_x = mat[0][3]
            frame.hmd_pos_y = mat[1][3]
            frame.hmd_pos_z = mat[2][3]
            
            # Note: A helper function is required here to convert the 3x3 rotation matrix 
            # to quaternions (rot_x, rot_y, rot_z, rot_w) for AI normalization.
            frame.hmd_tracking_valid = 1.0

        # 2. Controllers
        for i in range(1, openvr.k_unMaxTrackedDeviceCount):
            pose = self.poses[i]
            if not pose.bPoseIsValid:
                continue
                
            device_class = self.vr_system.getTrackedDeviceClass(i)
            if device_class == openvr.TrackedDeviceClass_Controller:
                role = self.vr_system.getControllerRoleForTrackedDeviceIndex(i)
                mat = pose.mDeviceToAbsoluteTracking
                
                if role == openvr.TrackedControllerRole_LeftHand:
                    frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = mat[0][3], mat[1][3], mat[2][3]
                    frame.left_tracking_valid = 1.0
                elif role == openvr.TrackedControllerRole_RightHand:
                    frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = mat[0][3], mat[1][3], mat[2][3]
                    frame.right_tracking_valid = 1.0

        # 3. Eye Tracking
        # Note: OpenVR natively does not supply eye tracking. 
        # The frame object retains the 0.0 defaults from create_empty().

        return frame

    def shutdown(self) -> None:
        if self.vr_system:
            openvr.shutdown()
            self.vr_system = None