# src/backends/backend_openxr.py

import logging
import ctypes
import platform
import xr
from typing import Optional, List

from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame
from src.eye_tracking.factory import EyeTrackingFactory
from src.eye_tracking.base_driver import IEyeTrackingDriver

logger = logging.getLogger(__name__)

class OpenXRBackend(IVRBackend):
    """
    Production-grade OpenXR backend designed for Overlay and Background telemetry.
    Actively hunts for XR_EXTX_overlay or XR_MND_headless to bypass rendering requirements,
    and manages OpenXR focus states to intercept telemetry without stealing primary app focus.
    """

    def __init__(self) -> None:
        self.instance: Optional[xr.Instance] = None
        self.system_id: Optional[xr.SystemId] = None
        self.session: Optional[xr.Session] = None
        self.app_space: Optional[xr.Space] = None

        self.action_set: Optional[xr.ActionSet] = None
        self.left_pose_action: Optional[xr.Action] = None
        self.right_pose_action: Optional[xr.Action] = None
        self.left_space: Optional[xr.Space] = None
        self.right_space: Optional[xr.Space] = None

        self.eye_driver: Optional[IEyeTrackingDriver] = None
        
        self.is_overlay = False
        self.is_headless = False
        self.session_state = xr.SessionState.UNKNOWN

        # Pre-allocated structures for zero-allocation poll loop
        self.active_action_set_info = xr.ActiveActionSet()
        self.actions_sync_info = xr.ActionsSyncInfo()
        self.view_locate_info = xr.ViewLocateInfo(view_configuration_type=xr.ViewConfigurationType.PRIMARY_STEREO)
        self.frame_end_info = xr.FrameEndInfo(environment_blend_mode=xr.EnvironmentBlendMode.OPAQUE)

    def initialize(self) -> bool:
        try:
            available_extensions = [ext.extension_name for ext in xr.enumerate_instance_extension_properties()]
            enabled_extensions = []

            # Overlay > Headless > Standard
            if "XR_EXTX_overlay" in available_extensions:
                enabled_extensions.append("XR_EXTX_overlay")
                self.is_overlay = True
                logger.info("Overlay extension XR_EXTX_overlay detected. Binding as compositor overlay.")
            elif "XR_MND_headless" in available_extensions:
                enabled_extensions.append("XR_MND_headless")
                self.is_headless = True
                logger.info("Headless extension XR_MND_headless detected. Binding as background service.")
            else:
                logger.warning("No overlay or headless extensions detected. Runtimes may block background execution.")

            # Dynamic biometric driver resolution
            self.eye_driver = EyeTrackingFactory.create_best_driver(available_extensions)
            if self.eye_driver:
                enabled_extensions.append(self.eye_driver.get_extension_name())
                for req_ext in self.eye_driver.get_additional_extensions():
                    if req_ext in available_extensions:
                        enabled_extensions.append(req_ext)

            self.instance = xr.create_instance(
                create_info=xr.InstanceCreateInfo(
                    application_info=xr.ApplicationInfo(
                        application_name="VRTelemetry_Overlay",
                        api_version=xr.XR_CURRENT_API_VERSION
                    ),
                    enabled_extension_names=enabled_extensions
                )
            )

            self.system_id = xr.get_system(self.instance, xr.SystemGetInfo(xr.FormFactor.HEAD_MOUNTED_DISPLAY))
            
            # Create session info (add overlay flags if necessary via next chain)
            session_create_info = xr.SessionCreateInfo(system_id=self.system_id)
            if self.is_overlay:
                overlay_info = xr.SessionCreateInfoOverlayEXTX(session_create_flags=xr.SessionCreateFlagsEXTX.NONE)
                session_create_info.next = ctypes.cast(ctypes.pointer(overlay_info), ctypes.c_void_p)
                
            self.session = xr.create_session(self.instance, session_create_info)
            self.app_space = xr.create_reference_space(self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.STAGE))

            self._setup_actions()

            if self.eye_driver:
                self.eye_driver.initialize(self.instance, self.session, self.app_space)

            self.active_action_set_info.action_set = self.action_set
            self.active_action_set_info.subaction_path = xr.NULL_PATH
            self.actions_sync_info.active_action_sets = [self.active_action_set_info]
            self.view_locate_info.space = self.app_space

            logger.info("OpenXR Overlay context established successfully.")
            return True

        except xr.XrException as e:
            logger.error(f"OpenXR Context Binding Exception: {e}")
            self.shutdown()
            return False

    def _setup_actions(self) -> None:
        self.action_set = xr.create_action_set(
            self.instance, xr.ActionSetCreateInfo(action_set_name="telemetry_set", localized_action_set_name="Telemetry Set")
        )
        self.left_pose_action = xr.create_action(
            self.action_set, xr.ActionCreateInfo(action_name="left_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Left Pose")
        )
        self.right_pose_action = xr.create_action(
            self.action_set, xr.ActionCreateInfo(action_name="right_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Right Pose")
        )

        xr.suggest_interaction_profile_bindings(
            self.instance,
            xr.InteractionProfileSuggestedBinding(
                interaction_profile=xr.string_to_path(self.instance, "/interaction_profiles/khr/simple_controller"),
                suggested_bindings=[
                    xr.ActionSuggestedBinding(self.left_pose_action, xr.string_to_path(self.instance, "/user/hand/left/input/grip/pose")),
                    xr.ActionSuggestedBinding(self.right_pose_action, xr.string_to_path(self.instance, "/user/hand/right/input/grip/pose"))
                ]
            )
        )

        self.left_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.left_pose_action))
        self.right_space = xr.create_action_space(self.session, xr.ActionSpaceCreateInfo(action=self.right_pose_action))
        xr.attach_action_sets(self.session, xr.SessionActionSetsAttachInfo(action_sets=[self.action_set]))

    def _pump_events(self) -> None:
        while True:
            event = xr.poll_event(self.instance)
            if event is None:
                break
            if isinstance(event, xr.EventDataSessionStateChanged):
                self.session_state = event.state
                logger.info(f"OpenXR Session State Transitioned to: {self.session_state}")
                if self.session_state == xr.SessionState.READY:
                    xr.begin_session(self.session, xr.SessionBeginInfo(xr.ViewConfigurationType.PRIMARY_STEREO))
                elif self.session_state == xr.SessionState.STOPPING:
                    xr.end_session(self.session)

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.session:
            return frame

        self._pump_events()
        
        # If the session isn't tracking, avoid querying hardware to prevent blocking errors
        if self.session_state not in (xr.SessionState.VISIBLE, xr.SessionState.FOCUSED):
            return frame

        try:
            state = xr.wait_frame(self.session)
            xr.begin_frame(self.session)
            t = state.predicted_display_time
            frame.timestamp_ns = t
            
            # Action sync must occur even if focus is lost (though it might return inactive states)
            xr.sync_actions(self.session, self.actions_sync_info)

            # HMD Evaluation
            self.view_locate_info.display_time = t
            v_state, views = xr.locate_views(self.session, self.view_locate_info)
            if len(views) > 0 and (v_state.view_state_flags & xr.VIEW_STATE_POSITION_VALID_BIT):
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = views[0].pose.position.x, views[0].pose.position.y, views[0].pose.position.z
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = views[0].pose.orientation.x, views[0].pose.orientation.y, views[0].pose.orientation.z, views[0].pose.orientation.w
                frame.hmd_tracking_valid = 1.0

            # Eye Tracking evaluation - delegates to the vendor-specific implementation
            if self.eye_driver:
                self.eye_driver.populate_frame(frame, t)

            self.frame_end_info.display_time = t
            xr.end_frame(self.session, self.frame_end_info)

        except Exception as e:
            logger.debug(f"Frame synchronization fault: {e}")

        return frame

    def shutdown(self) -> None:
        if self.eye_driver: self.eye_driver.shutdown()
        if self.left_space: xr.destroy_space(self.left_space)
        if self.right_space: xr.destroy_space(self.right_space)
        if self.app_space: xr.destroy_space(self.app_space)
        if self.action_set: xr.destroy_action_set(self.action_set)
        if self.session: xr.destroy_session(self.session)
        if self.instance: xr.destroy_instance(self.instance)
        logger.info("OpenXR Overlay Context Safely Terminated.")