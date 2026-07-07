import sys
import numpy as np
import xr
from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame
import glfw
from OpenGL.GL import *
from ctypes import windll
GetDC = windll.user32.GetDC

class OpenXRBackend(IVRBackend):
    """
    Production OpenXR abstraction implementation. Resolves action spatial relationships
    via explicit bindings for multi-device cross-compatibility, including native Eye Gaze.
    """
    def __init__(self):
        self.instance = None
        self.system = None
        self.session = None
        self.app_space = None
        self.has_eye_tracking = False
        
        # Action mappings for data tracking pipelines
        self.action_set = None
        self.left_pose_action = None
        self.right_pose_action = None
        self.left_space = None
        self.right_space = None
        
        # Analog/Binary inputs
        self.left_trigger_action = None
        self.right_trigger_action = None

        # Eye Tracking Action Spaces
        self.eye_gaze_action = None
        self.eye_space = None
        
        self.window = None

    def initialize(self) -> bool:
        if not glfw.init(): return False
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        self.window = glfw.create_window(640, 480, "Dummy", None, None)
        glfw.make_context_current(self.window)
        
        hwnd = glfw.get_win32_window(self.window)
        hdc = GetDC(hwnd)
        
        try:
            available = [e.extension_name for e in xr.enumerate_instance_extension_properties()]
            enabled = []
            
            # 1. Ask OpenXR to allow us to run without a 3D graphics window
            if "XR_MND_headless" in available:
                enabled.append("XR_MND_headless")
            
            # 2. Ask OpenXR to expose the eye tracking datastream
            if "XR_EXT_eye_gaze_interaction" in available:
                enabled.append("XR_EXT_eye_gaze_interaction")
                self.has_eye_tracking = True
            
            self.instance = xr.create_instance(
                create_info=xr.InstanceCreateInfo(
                    application_info=xr.ApplicationInfo(
                        application_name="VRTelemetry_Pro",
                        api_version=xr.XR_CURRENT_API_VERSION
                    ),
                    enabled_extension_names=enabled
                )
            )
            
            self.system = xr.get_system(self.instance, xr.SystemGetInfo(xr.FormFactor.HEAD_MOUNTED_DISPLAY))
            
            self.session = xr.create_session(self.instance, xr.SessionCreateInfo(system_id=self.system))
            hwnd = glfw.get_win32_window(self.window)
            hglrc = glfw.get_current_context()
            hdc = wglGetCurrentDC()
            
            graphics_binding = xr.GraphicsBindingOpenGLWin32KHR(
                h_dc=hdc,
                h_glrc=hglrc
            )
            self.app_space = xr.create_reference_space(self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.STAGE))
            
            self._setup_actions()
            return True
        except Exception as e:
            print(f"[*] OpenXR context binding bypassed: {e}")
            self.shutdown()
            return False

    def _setup_actions(self) -> None:
        self.action_set = xr.create_action_set(self.instance, xr.ActionSetCreateInfo(action_set_name="telemetry_set", localized_action_set_name="Telemetry Set"))
        
        self.left_pose_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="left_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Left Pose"))
        self.right_pose_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="right_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Right Pose"))
        self.left_trigger_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="left_trigger", action_type=xr.ActionType.FLOAT_INPUT, localized_action_name="Left Trigger"))
        self.right_trigger_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="right_trigger", action_type=xr.ActionType.FLOAT_INPUT, localized_action_name="Right Trigger"))
        
        # Add Eye Tracking Action
        if self.has_eye_tracking:
            self.eye_gaze_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="eye_gaze", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Eye Gaze"))

        # Suggest bindings for Oculus Touch Controllers
        xr.suggest_interaction_profile_bindings(
            self.instance,
            xr.InteractionProfileSuggestedBinding(
                interaction_profile=xr.string_to_path(self.instance, "/interaction_profiles/oculus/touch_controller"),
                suggested_bindings=[
                    xr.ActionSuggestedBinding(self.left_pose_action, xr.string_to_path(self.instance, "/user/hand/left/input/grip/pose")),
                    xr.ActionSuggestedBinding(self.right_pose_action, xr.string_to_path(self.instance, "/user/hand/right/input/grip/pose")),
                    xr.ActionSuggestedBinding(self.left_trigger_action, xr.string_to_path(self.instance, "/user/hand/left/input/trigger/value")),
                    xr.ActionSuggestedBinding(self.right_trigger_action, xr.string_to_path(self.instance, "/user/hand/right/input/trigger/value"))
                ]
            )
        )

        # Suggest bindings for Eye Gaze
        if self.has_eye_tracking:
            xr.suggest_interaction_profile_bindings(
                self.instance,
                xr.InteractionProfileSuggestedBinding(
                    interaction_profile=xr.string_to_path(self.instance, "/interaction_profiles/ext/eye_gaze_interaction"),
                    suggested_bindings=[
                        xr.ActionSuggestedBinding(self.eye_gaze_action, xr.string_to_path(self.instance, "/user/eyes_ext/input/gaze_ext/pose"))
                    ]
                )
            )
            self.eye_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.eye_gaze_action))
        
        self.left_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.left_pose_action))
        self.right_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.right_pose_action))
        xr.attach_action_sets(self.session, xr.SessionActionSetsAttachInfo(action_sets=[self.action_set]))

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.session:
            return frame

        try:
            state = xr.wait_frame(self.session)
            xr.begin_frame(self.session)
            t = state.predicted_display_time
            
            xr.sync_actions(self.session, xr.ActionsSyncInfo(active_action_sets=[xr.ActiveActionSet(self.action_set)]))

            # Add this debug block to see if the runtime is even attempting to give you eye data
            if self.has_eye_tracking:
                gaze_state = xr.get_action_state_pose(self.session, xr.ActionStateGetInfo(self.eye_gaze_action))
                print(f"DEBUG: Eye Action State - Active: {gaze_state.is_active}, Changed: {gaze_state.changed_since_last_sync}")
    
            # 1. HMD Position Evaluation
            v_state, views = xr.locate_views(self.session, xr.ViewLocateInfo(xr.ViewConfigurationType.PRIMARY_STEREO, t, self.app_space))
            if len(views) > 0 and (v_state.view_state_flags & xr.VIEW_STATE_POSITION_VALID_BIT):
                pos = views[0].pose.position
                rot = views[0].pose.orientation
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = pos.x, pos.y, pos.z
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = rot.x, rot.y, rot.z, rot.w
                frame.hmd_tracking_valid = 1.0

            # 2. Left Controller Evaluation
            l_loc = xr.locate_space(self.left_space, self.app_space, t)
            if l_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = l_loc.pose.position.x, l_loc.pose.position.y, l_loc.pose.position.z
                frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = l_loc.pose.orientation.x, l_loc.pose.orientation.y, l_loc.pose.orientation.z, l_loc.pose.orientation.w
                frame.left_tracking_valid = 1.0

            # 3. Right Controller Evaluation
            r_loc = xr.locate_space(self.right_space, self.app_space, t)
            if r_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = r_loc.pose.position.x, r_loc.pose.position.y, r_loc.pose.position.z
                frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = r_loc.pose.orientation.x, r_loc.pose.orientation.y, r_loc.pose.orientation.z, r_loc.pose.orientation.w
                frame.right_tracking_valid = 1.0

            # 4. Native Eye Tracking Evaluation
            if self.has_eye_tracking and self.eye_space:
                eye_loc = xr.locate_space(self.eye_space, self.app_space, t)
                
                # Verify that the headset can currently see your eyes
                if eye_loc.location_flags & xr.SPACE_LOCATION_ORIENTATION_VALID_BIT:
                    # OpenXR provides a single unified gaze ray. We map it to both eyes for the struct.
                    pos = eye_loc.pose.position
                    rot = eye_loc.pose.orientation
                    
                    frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z = pos.x, pos.y, pos.z
                    frame.left_eye_rot_x, frame.left_eye_rot_y, frame.left_eye_rot_z, frame.left_eye_rot_w = rot.x, rot.y, rot.z, rot.w
                    
                    frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z = pos.x, pos.y, pos.z
                    frame.right_eye_rot_x, frame.right_eye_rot_y, frame.right_eye_rot_z, frame.right_eye_rot_w = rot.x, rot.y, rot.z, rot.w
                    
                    frame.eye_tracking_valid = 1.0

            xr.end_frame(self.session, xr.FrameEndInfo(t, xr.EnvironmentBlendMode.OPAQUE))
        except Exception as e:
            pass 
        return frame

    def shutdown(self) -> None:
        if self.eye_space: xr.destroy_space(self.eye_space)
        if self.left_space: xr.destroy_space(self.left_space)
        if self.right_space: xr.destroy_space(self.right_space)
        if self.app_space: xr.destroy_space(self.app_space)
        if self.session: xr.destroy_session(self.session)
        if self.instance: xr.destroy_instance(self.instance)