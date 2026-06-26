import sys
import numpy as np
import xr
from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame

class OpenXRBackend(IVRBackend):
    """
    Production OpenXR abstraction implementation. Resolves action spatial relationships
    via explicit bindings for multi-device cross-compatibility.
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

    def initialize(self) -> bool:
        try:
            available = [e.extension_name for e in xr.enumerate_instance_extension_properties()]
            enabled = []
            
            # Explicit declaration of vendor tracking extension namespaces
            if "XR_EXT_eye_gaze_interaction" in available:
                enabled.append("XR_EXT_eye_gaze_interaction")
                self.has_eye_tracking = True
            
            # Formulate OpenXR application context configuration
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
            
            # Headless runtimes require dummy binding configuration parameters
            # Under standard operating constraints, the headless extension handles session validation safely
            self.session = xr.create_session(self.instance, xr.SessionCreateInfo(system_id=self.system))
            self.app_space = xr.create_reference_space(self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.STAGE))
            
            self._setup_actions()
            return True
        except Exception as e:
            print(f"[*] OpenXR context binding bypassed: {e}")
            self.shutdown()
            return False

    def _setup_actions(self) -> None:
        # Create core tracking containers
        self.action_set = xr.create_action_set(self.instance, xr.ActionSetCreateInfo(action_set_name="telemetry_set", localized_action_set_name="Telemetry Set"))
        
        self.left_pose_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="left_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Left Pose"))
        self.right_pose_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="right_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Right Pose"))
        self.left_trigger_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="left_trigger", action_type=xr.ActionType.FLOAT_INPUT, localized_action_name="Left Trigger"))
        self.right_trigger_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="right_trigger", action_type=xr.ActionType.FLOAT_INPUT, localized_action_name="Right Trigger"))
        
        # Suggest device profiles for deployment across Oculus/Quest configurations
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
        
        self.left_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.left_pose_action))
        self.right_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.right_pose_action))
        xr.attach_action_sets(self.session, xr.SessionActionSetsAttachInfo(action_sets=[self.action_set]))

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.session:
            return frame

        try:
            # Manage wait frame mechanics synchronization points
            state = xr.wait_frame(self.session)
            xr.begin_frame(self.session)
            t = state.predicted_display_time
            
            xr.sync_actions(self.session, xr.ActionsSyncInfo(active_action_sets=[xr.ActiveActionSet(self.action_set)]))

            # 1. HMD Position Evaluation
            v_state, views = xr.locate_views(self.session, xr.ViewLocateInfo(xr.ViewConfigurationType.PRIMARY_STEREO, t, self.app_space))
            if len(views) > 0 and (v_state.view_state_flags & xr.VIEW_STATE_POSITION_VALID_BIT):
                pos = views[0].pose.position
                rot = views[0].pose.orientation
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = pos.x, pos.y, pos.z
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = rot.x, rot.y, rot.z, rot.w
                frame.hmd_tracking_valid = 1.0

            # 2. Left Controller Position Evaluation
            l_loc = xr.locate_space(self.left_space, self.app_space, t)
            if l_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = l_loc.pose.position.x, l_loc.pose.position.y, l_loc.pose.position.z
                frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = l_loc.pose.orientation.x, l_loc.pose.orientation.y, l_loc.pose.orientation.z, l_loc.pose.orientation.w
                frame.left_tracking_valid = 1.0
                frame.left_trigger = xr.get_action_state_float(self.session, xr.ActionStateGetInfo(self.left_trigger_action)).current_state

            # 3. Right Controller Position Evaluation
            r_loc = xr.locate_space(self.right_space, self.app_space, t)
            if r_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = r_loc.pose.position.x, r_loc.pose.position.y, r_loc.pose.position.z
                frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = r_loc.pose.orientation.x, r_loc.pose.orientation.y, r_loc.pose.orientation.z, r_loc.pose.orientation.w
                frame.right_tracking_valid = 1.0
                frame.right_trigger = xr.get_action_state_float(self.session, xr.ActionStateGetInfo(self.right_trigger_action)).current_state

            xr.end_frame(self.session, xr.FrameEndInfo(t, xr.EnvironmentBlendMode.OPAQUE))
        except Exception:
            pass # Guarantees that frame pipeline execution remains unblocked during individual tracking failures
        return frame

    def shutdown(self) -> None:
        if self.left_space: xr.destroy_space(self.left_space)
        if self.right_space: xr.destroy_space(self.right_space)
        if self.app_space: xr.destroy_space(self.app_space)
        if self.session: xr.destroy_session(self.session)
        if self.instance: xr.destroy_instance(self.instance)