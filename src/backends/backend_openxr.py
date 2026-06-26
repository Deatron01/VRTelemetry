import time
import xr  # pyopenxr
from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame

class OpenXRBackend(IVRBackend):
    """
    Primary backend utilizing the OpenXR runtime. 
    Compatible with Quest, Windows Mixed Reality, Pico, and Vive (via SteamVR OpenXR).
    """
    def __init__(self):
        self.instance = None
        self.system_id = None
        self.session = None
        self.space_app = None
        
        # Feature Flags
        self.has_eye_tracking = False

    def initialize(self) -> bool:
        try:
            # 1. Discover Extensions (Check for Eye Tracking)
            available_extensions = [ext.extension_name for ext in xr.enumerate_instance_extension_properties()]
            req_extensions = []
            
            if "XR_EXT_eye_gaze_interaction" in available_extensions:
                req_extensions.append("XR_EXT_eye_gaze_interaction")
                self.has_eye_tracking = True

            # 2. Create Instance
            self.instance = xr.create_instance(
                create_info=xr.InstanceCreateInfo(
                    application_info=xr.ApplicationInfo(
                        application_name="VRTelemetry_Pro",
                        application_version=1,
                        engine_name="NativePython",
                        engine_version=1,
                        api_version=xr.XR_CURRENT_API_VERSION
                    ),
                    enabled_extension_names=req_extensions
                )
            )

            # 3. Get HMD System
            self.system_id = xr.get_system(
                self.instance, 
                xr.SystemGetInfo(form_factor=xr.FormFactor.HEAD_MOUNTED_DISPLAY)
            )

            # 4. Create Session (Graphics binding omitted for telemetry-only headless mode)
            # Note: For strict headless telemetry, some runtimes require a dummy graphics binding.
            self.session = xr.create_session(
                self.instance, 
                xr.SessionCreateInfo(system_id=self.system_id)
            )

            # 5. Create Reference Space (Stage or Local)
            self.space_app = xr.create_reference_space(
                self.session,
                xr.ReferenceSpaceCreateInfo(
                    reference_space_type=xr.ReferenceSpaceType.STAGE,
                    pose_in_reference_space=xr.Posef(
                        orientation=xr.Quaternionf(0, 0, 0, 1),
                        position=xr.Vector3f(0, 0, 0)
                    )
                )
            )
            return True
        except xr.XrException as e:
            print(f"[*] OpenXR Initialization failed (Runtime unavailable or sleeping): {e}")
            self.shutdown()
            return False

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        # Base frame pre-filled with 0.0s to prevent missing data errors
        frame = TelemetryFrame.create_empty(frame_index)
        
        if not self.session:
            return frame

        # Fetch prediction time for the current frame
        frame_state = xr.wait_frame(self.session)
        xr.begin_frame(self.session)
        
        target_time = frame_state.predicted_display_time

        # 1. Poll HMD Pose
        try:
            view_state, views = xr.locate_views(
                self.session, 
                xr.ViewLocateInfo(view_configuration_type=xr.ViewConfigurationType.PRIMARY_STEREO, display_time=target_time)
            )
            if view_state.view_state_flags & xr.VIEW_STATE_POSITION_VALID_BIT:
                # Use left eye view for HMD root approximation, or average them
                pose = views[0].pose
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = pose.position.x, pose.position.y, pose.position.z
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w
                frame.hmd_tracking_valid = 1.0
        except xr.XrException:
            pass # Tracking lost, fallback to 0.0s inherently handled by create_empty()

        # 2. Poll Controllers (Action Spaces)
        # Note: In a full implementation, you sync actions here via xr.sync_actions()
        # and query the action states and action spaces for L/R controllers.
        self._poll_controllers(frame, target_time)

        # 3. Poll Eye Tracking (If Extension Valid)
        if self.has_eye_tracking:
            self._poll_eye_gaze(frame, target_time)

        xr.end_frame(self.session, xr.FrameEndInfo(display_time=target_time, environment_blend_mode=xr.EnvironmentBlendMode.OPAQUE))
        
        return frame

    def _poll_controllers(self, frame: TelemetryFrame, target_time: int) -> None:
        # To be implemented: xr.locate_space for action_space_left and action_space_right
        pass

    def _poll_eye_gaze(self, frame: TelemetryFrame, target_time: int) -> None:
        # To be implemented: xr.locate_space for eye_gaze_space
        pass

    def shutdown(self) -> None:
        if self.space_app: xr.destroy_space(self.space_app)
        if self.session: xr.destroy_session(self.session)
        if self.instance: xr.destroy_instance(self.instance)