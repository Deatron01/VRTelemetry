# src/backends/backend_openxr.py

import time 
import logging
import ctypes
import xr
from typing import Optional, List

from src.core.interfaces import IVRBackend
from src.core.datatypes import TelemetryFrame
from src.eye_tracking.factory import EyeTrackingFactory
from src.eye_tracking.base_driver import IEyeTrackingDriver

logger = logging.getLogger(__name__)

class OpenXRBackend(IVRBackend):
    """
    Production-grade OpenXR backend.
    Hunts for XR_MND_headless to execute silently in the background, 
    and handles unified session attachments for external biometric drivers.
    """

    def __init__(self) -> None:
        self.refresh_rate_hz: Optional[float] = None
        
        self.instance: Optional[xr.Instance] = None
        self.system_id: Optional[xr.SystemId] = None
        self.session: Optional[xr.Session] = None
        self.app_space: Optional[xr.Space] = None
        self.view_space: Optional[xr.Space] = None

        self.action_set: Optional[xr.ActionSet] = None
        self.left_pose_action: Optional[xr.Action] = None
        self.right_pose_action: Optional[xr.Action] = None
        self.left_trigger_action: Optional[xr.Action] = None
        self.right_trigger_action: Optional[xr.Action] = None
        
        self.left_space: Optional[xr.Space] = None
        self.right_space: Optional[xr.Space] = None

        self.eye_driver: Optional[IEyeTrackingDriver] = None
        
        self.is_headless = False
        self.session_state = xr.SessionState.UNKNOWN

        self.frame_end_info = xr.FrameEndInfo(environment_blend_mode=xr.EnvironmentBlendMode.OPAQUE)
        
        # Memory-safe array references to prevent ctypes garbage collection
        self._action_sets_arr = None
        self._active_action_sets_arr = None
        self.actions_sync_info = xr.ActionsSyncInfo()

    def initialize(self) -> bool:
        try:
            available_extensions = [
                ext.extension_name.decode('utf-8') if isinstance(ext.extension_name, bytes) else ext.extension_name
                for ext in xr.enumerate_instance_extension_properties()
            ]
            enabled_extensions = []
            
            if "XR_FB_display_refresh_rate" in available_extensions:
                enabled_extensions.append("XR_FB_display_refresh_rate")

            if "XR_MND_headless" in available_extensions:
                enabled_extensions.append("XR_MND_headless")
                self.is_headless = True
                logger.info("Headless extension XR_MND_headless detected. Binding as background service.")
            else:
                logger.error("XR_MND_headless not found. Cannot run background telemetry without a graphics context.")
                return False

            self.eye_driver = EyeTrackingFactory.create_best_driver(available_extensions)
            if self.eye_driver:
                enabled_extensions.append(self.eye_driver.get_extension_name())
                for req_ext in self.eye_driver.get_additional_extensions():
                    if req_ext in available_extensions:
                        enabled_extensions.append(req_ext)

            self.instance = xr.create_instance(
                create_info=xr.InstanceCreateInfo(
                    application_info=xr.ApplicationInfo(
                        application_name="VRTelemetry_Engine",
                        api_version=xr.Version(1, 0, 0)
                    ),
                    enabled_extension_names=enabled_extensions
                )
            )

            self.system_id = xr.get_system(self.instance, xr.SystemGetInfo(xr.FormFactor.HEAD_MOUNTED_DISPLAY))
            
            session_create_info = xr.SessionCreateInfo(system_id=self.system_id)
            self.session = xr.create_session(self.instance, session_create_info)
            self._query_refresh_rate(enabled_extensions)
            
            try:
                self.app_space = xr.create_reference_space(self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.LOCAL))
            except Exception:
                self.app_space = xr.create_reference_space(self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.STAGE))

            self._setup_actions()

            if self.eye_driver:
                self.eye_driver.initialize(self.instance, self.session, self.app_space)

            # --- STRICT MEMORY ALLOCATION FOR ACTION SETS ---
            action_sets_to_attach = [self.action_set]
            active_action_sets = []
            
            active_main = xr.ActiveActionSet(action_set=self.action_set, subaction_path=xr.NULL_PATH)
            active_action_sets.append(active_main)
            
            if self.eye_driver and getattr(self.eye_driver, 'gaze_action_set', None):
                action_sets_to_attach.append(self.eye_driver.gaze_action_set)
                active_eye = xr.ActiveActionSet(action_set=self.eye_driver.gaze_action_set, subaction_path=xr.NULL_PATH)
                active_action_sets.append(active_eye)

            # Retain strict C-references to prevent Python GC from destroying the handles
            self._action_sets_arr = (xr.ActionSet * len(action_sets_to_attach))(*action_sets_to_attach)
            xr.attach_session_action_sets(
                self.session, 
                xr.SessionActionSetsAttachInfo(
                    count_action_sets=len(self._action_sets_arr),
                    action_sets=self._action_sets_arr
                )
            )

            self._active_action_sets_arr = (xr.ActiveActionSet * len(active_action_sets))(*active_action_sets)
            self.actions_sync_info = xr.ActionsSyncInfo(
                count_active_action_sets=len(self._active_action_sets_arr),
                active_action_sets=self._active_action_sets_arr
            )

            logger.info("OpenXR Context established successfully with unified spatial tracking.")
            return True

        except xr.XrException as e:
            logger.error(f"OpenXR Context Binding Exception: {e}")
            self.shutdown()
            return False

    def _setup_actions(self) -> None:
        self.action_set = xr.create_action_set(
            self.instance, xr.ActionSetCreateInfo(action_set_name="telemetry_set", localized_action_set_name="Telemetry Set")
        )
        
        self.left_pose_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="left_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Left Pose"))
        self.right_pose_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="right_pose", action_type=xr.ActionType.POSE_INPUT, localized_action_name="Right Pose"))
        self.left_trigger_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="left_trigger", action_type=xr.ActionType.FLOAT_INPUT, localized_action_name="Left Trigger"))
        self.right_trigger_action = xr.create_action(self.action_set, xr.ActionCreateInfo(action_name="right_trigger", action_type=xr.ActionType.FLOAT_INPUT, localized_action_name="Right Trigger"))

        xr.suggest_interaction_profile_bindings(
            self.instance,
            xr.InteractionProfileSuggestedBinding(
                interaction_profile=xr.string_to_path(self.instance, "/interaction_profiles/htc/vive_controller"),
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
        self.view_space = xr.create_reference_space(self.session, xr.ReferenceSpaceCreateInfo(reference_space_type=xr.ReferenceSpaceType.VIEW))

    def _pump_events(self) -> None:
        while True:
            try:
                event = xr.poll_event(self.instance)
                event_type = getattr(event, "type", None)
                
                if event_type == xr.StructureType.EVENT_DATA_SESSION_STATE_CHANGED or isinstance(event, xr.EventDataSessionStateChanged):
                    if not isinstance(event, xr.EventDataSessionStateChanged):
                        event = ctypes.cast(ctypes.byref(event), ctypes.POINTER(xr.EventDataSessionStateChanged)).contents
                        
                    self.session_state = event.state
                    
                    if self.session_state == xr.SessionState.READY:
                        xr.begin_session(self.session, xr.SessionBeginInfo(xr.ViewConfigurationType.PRIMARY_STEREO))
                    elif self.session_state == xr.SessionState.STOPPING:
                        xr.end_session(self.session)
            except xr.EventUnavailable:
                break

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.session:
            time.sleep(0.01)
            return frame

        self._pump_events()
        
        if self.session_state not in (xr.SessionState.VISIBLE, xr.SessionState.FOCUSED, xr.SessionState.SYNCHRONIZED):
            time.sleep(0.02) 
            return frame

        # Fallback absolute time in case the runtime refuses to predict one
        t = time.perf_counter_ns()
        
        try:
            state = xr.wait_frame(self.session)
            xr.begin_frame(self.session)
            
            if state.predicted_display_time > 0:
                t = state.predicted_display_time
                
            frame.timestamp_ns = t
            
            try:
                xr.sync_actions(self.session, self.actions_sync_info)
            except Exception as sync_err:
                logger.debug(f"OpenXR Sync Actions Failed: {sync_err}")

            # 1. HMD Evaluation
            if self.view_space:
                try:
                    view_loc = xr.locate_space(self.view_space, self.app_space, t)
                    if view_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                        frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = view_loc.pose.position.x, view_loc.pose.position.y, view_loc.pose.position.z
                        frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = view_loc.pose.orientation.x, view_loc.pose.orientation.y, view_loc.pose.orientation.z, view_loc.pose.orientation.w
                        frame.hmd_tracking_valid = 1.0
                except Exception:
                    pass

            # 2. Controllers
            if self.left_space:
                try:
                    left_loc = xr.locate_space(self.left_space, self.app_space, t)
                    if left_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                        frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = left_loc.pose.position.x, left_loc.pose.position.y, left_loc.pose.position.z
                        frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = left_loc.pose.orientation.x, left_loc.pose.orientation.y, left_loc.pose.orientation.z, left_loc.pose.orientation.w
                        frame.left_tracking_valid = 1.0
                        
                        left_trig = xr.get_action_state_float(self.session, xr.ActionStateGetInfo(action=self.left_trigger_action))
                        if left_trig.is_active: frame.left_trigger = left_trig.current_state
                except Exception:
                    pass

            if self.right_space:
                try:
                    right_loc = xr.locate_space(self.right_space, self.app_space, t)
                    if right_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                        frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = right_loc.pose.position.x, right_loc.pose.position.y, right_loc.pose.position.z
                        frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = right_loc.pose.orientation.x, right_loc.pose.orientation.y, right_loc.pose.orientation.z, right_loc.pose.orientation.w
                        frame.right_tracking_valid = 1.0
                        
                        right_trig = xr.get_action_state_float(self.session, xr.ActionStateGetInfo(action=self.right_trigger_action))
                        if right_trig.is_active: frame.right_trigger = right_trig.current_state
                except Exception:
                    pass

            # 3. Eye Tracking Evaluation
            if self.eye_driver:
                try:
                    self.eye_driver.populate_frame(frame, t)
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Frame lifecycle fault: {e}")
            
        finally:
            # We MUST end the frame to keep the session alive, but we can safely ignore the headless discard warning
            try:
                self.frame_end_info.display_time = t
                xr.end_frame(self.session, self.frame_end_info)
            except Exception as end_err:
                if "discarded" not in str(end_err).lower():
                    logger.debug(f"End frame exception: {end_err}")

        return frame

    def shutdown(self) -> None:
        if self.eye_driver: 
            self.eye_driver.shutdown()
            self.eye_driver = None
        if self.view_space: 
            xr.destroy_space(self.view_space)
            self.view_space = None
        if self.left_space: 
            xr.destroy_space(self.left_space)
            self.left_space = None
        if self.right_space: 
            xr.destroy_space(self.right_space)
            self.right_space = None
        if self.app_space: 
            xr.destroy_space(self.app_space)
            self.app_space = None
        if self.action_set: 
            xr.destroy_action_set(self.action_set)
            self.action_set = None
        if self.session: 
            xr.destroy_session(self.session)
            self.session = None
        if self.instance: 
            xr.destroy_instance(self.instance)
            self.instance = None
            
        logger.info("OpenXR Context Safely Terminated.")
    
    def _query_refresh_rate(self, enabled_extensions: list) -> None:
        if "XR_FB_display_refresh_rate" not in enabled_extensions:
            return
        try:
            get_rate_fn = xr.get_instance_proc_addr(self.instance, "xrGetDisplayRefreshRateFB")
            if not get_rate_fn:
                return
            rate = ctypes.c_float()
            func = ctypes.CFUNCTYPE(
                xr.Result, xr.Session, ctypes.POINTER(ctypes.c_float)
            )(get_rate_fn)
            res = func(self.session, ctypes.byref(rate))
            if not xr.Result(res).is_exception() and rate.value > 0:
                self.refresh_rate_hz = float(rate.value)
                logger.info(f"Live HMD refresh rate reported by runtime: {self.refresh_rate_hz:.1f} Hz")
        except Exception as e:
            logger.debug(f"Refresh rate query failed (non-critical): {e}")

    def get_refresh_rate_hz(self) -> Optional[float]:
        return self.refresh_rate_hz