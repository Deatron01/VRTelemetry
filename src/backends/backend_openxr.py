# src/backends/backend_openxr.py

import ctypes
import logging
import time

import xr

from src.backends.tracking_faults import TrackingFaultLog
from src.core.datatypes import TelemetryFrame
from src.core.interfaces import IVRBackend
from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory

logger = logging.getLogger(__name__)


class OpenXRBackend(IVRBackend):
    """
    Production-grade OpenXR backend.
    Hunts for XR_MND_headless to execute silently in the background,
    and handles unified session attachments for external biometric drivers.
    """

    #: OpenXR stamps frames with `predicted_display_time`.
    timestamp_is_display_time = True

    def __init__(self) -> None:
        self.refresh_rate_hz: float | None = None

        self.instance: xr.Instance | None = None
        self.system_id: xr.SystemId | None = None
        self.session: xr.Session | None = None
        self.app_space: xr.Space | None = None
        self.view_space: xr.Space | None = None

        self.action_set: xr.ActionSet | None = None
        self.left_pose_action: xr.Action | None = None
        self.right_pose_action: xr.Action | None = None
        self.left_trigger_action: xr.Action | None = None
        self.right_trigger_action: xr.Action | None = None

        self.left_space: xr.Space | None = None
        self.right_space: xr.Space | None = None

        self.eye_driver: IEyeTrackingDriver | None = None

        self.is_headless = False
        self.session_state = xr.SessionState.UNKNOWN

        self.frame_end_info = xr.FrameEndInfo(environment_blend_mode=xr.EnvironmentBlendMode.OPAQUE)

        #: Per-source tracking faults (VRT-13). Each `except` in poll_frame
        #: below records into this instead of `pass`-ing, so a session in which
        #: the left controller failed to locate on a third of its frames is
        #: distinguishable afterwards from one in which the subject simply put
        #: it down -- which produces byte-identical columns.
        self.faults = TrackingFaultLog("OpenXRBackend")
        self._frames_polled = 0

        # Memory-safe array references to prevent ctypes garbage collection.
        # Annotated Optional because that is what they are between construction
        # and initialize(); the reads below use the local lists they were built
        # from rather than re-deriving a length from an attribute the checker
        # cannot prove is set.
        self._action_sets_arr: ctypes.Array | None = None
        self._active_action_sets_arr: ctypes.Array | None = None
        self.actions_sync_info = xr.ActionsSyncInfo()

    def initialize(self) -> bool:
        try:
            available_extensions = [
                ext.extension_name.decode("utf-8")
                if isinstance(ext.extension_name, bytes)
                else ext.extension_name
                for ext in xr.enumerate_instance_extension_properties()
            ]
            enabled_extensions = []

            if "XR_FB_display_refresh_rate" in available_extensions:
                enabled_extensions.append("XR_FB_display_refresh_rate")

            if "XR_MND_headless" in available_extensions:
                enabled_extensions.append("XR_MND_headless")
                self.is_headless = True
                logger.info(
                    "Headless extension XR_MND_headless detected. Binding as background service."
                )
            else:
                logger.error(
                    "XR_MND_headless not found. Cannot run background telemetry without a graphics context."
                )
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
                        application_name="VRTelemetry_Engine", api_version=xr.Version(1, 0, 0)
                    ),
                    enabled_extension_names=enabled_extensions,
                )
            )

            self.system_id = xr.get_system(
                self.instance, xr.SystemGetInfo(xr.FormFactor.HEAD_MOUNTED_DISPLAY)
            )

            session_create_info = xr.SessionCreateInfo(system_id=self.system_id)
            self.session = xr.create_session(self.instance, session_create_info)
            self._query_refresh_rate(enabled_extensions)

            try:
                self.app_space = xr.create_reference_space(
                    self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.LOCAL)
                )
            except xr.XrException as local_err:
                # A runtime that offers no LOCAL space -- seated-only or
                # room-scale-only hardware. Narrowed to the runtime's own
                # exception type so a mistake in *our* call (a bad enum, a stale
                # session handle) is not silently retried as STAGE and then
                # reported as a STAGE failure, which is what made this branch
                # unreadable. If STAGE fails too, that error travels to
                # initialize()'s handler and the backend reports it cannot bind.
                logger.info(
                    f"LOCAL reference space unavailable, falling back to STAGE: {local_err}"
                )
                self.app_space = xr.create_reference_space(
                    self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.STAGE)
                )

            self._setup_actions()

            if self.eye_driver:
                self.eye_driver.initialize(self.instance, self.session, self.app_space)

            # --- STRICT MEMORY ALLOCATION FOR ACTION SETS ---
            action_sets_to_attach = [self.action_set]
            active_action_sets = []

            active_main = xr.ActiveActionSet(
                action_set=self.action_set, subaction_path=xr.NULL_PATH
            )
            active_action_sets.append(active_main)

            # `getattr(..., None)` until VRT-17, because IEyeTrackingDriver did
            # not declare the attribute -- so the backend was probing its own
            # port for a field it hoped one implementation would have. It is
            # part of the interface now.
            eye_action_set = self.eye_driver.gaze_action_set if self.eye_driver else None
            if eye_action_set is not None:
                action_sets_to_attach.append(eye_action_set)
                active_action_sets.append(
                    xr.ActiveActionSet(action_set=eye_action_set, subaction_path=xr.NULL_PATH)
                )

            # Retain strict C-references to prevent Python GC from destroying the handles
            action_sets_arr = (xr.ActionSet * len(action_sets_to_attach))(*action_sets_to_attach)
            self._action_sets_arr = action_sets_arr
            xr.attach_session_action_sets(
                self.session,
                xr.SessionActionSetsAttachInfo(
                    count_action_sets=len(action_sets_to_attach), action_sets=action_sets_arr
                ),
            )

            active_arr = (xr.ActiveActionSet * len(active_action_sets))(*active_action_sets)
            self._active_action_sets_arr = active_arr
            self.actions_sync_info = xr.ActionsSyncInfo(
                count_active_action_sets=len(active_action_sets),
                active_action_sets=active_arr,
            )

            logger.info("OpenXR Context established successfully with unified spatial tracking.")
            return True

        except xr.XrException as e:
            logger.error(f"OpenXR Context Binding Exception: {e}")
            self.shutdown()
            return False

    def _setup_actions(self) -> None:
        self.action_set = xr.create_action_set(
            self.instance,
            xr.ActionSetCreateInfo(
                action_set_name="telemetry_set", localized_action_set_name="Telemetry Set"
            ),
        )

        self.left_pose_action = xr.create_action(
            self.action_set,
            xr.ActionCreateInfo(
                action_name="left_pose",
                action_type=xr.ActionType.POSE_INPUT,
                localized_action_name="Left Pose",
            ),
        )
        self.right_pose_action = xr.create_action(
            self.action_set,
            xr.ActionCreateInfo(
                action_name="right_pose",
                action_type=xr.ActionType.POSE_INPUT,
                localized_action_name="Right Pose",
            ),
        )
        self.left_trigger_action = xr.create_action(
            self.action_set,
            xr.ActionCreateInfo(
                action_name="left_trigger",
                action_type=xr.ActionType.FLOAT_INPUT,
                localized_action_name="Left Trigger",
            ),
        )
        self.right_trigger_action = xr.create_action(
            self.action_set,
            xr.ActionCreateInfo(
                action_name="right_trigger",
                action_type=xr.ActionType.FLOAT_INPUT,
                localized_action_name="Right Trigger",
            ),
        )

        xr.suggest_interaction_profile_bindings(
            self.instance,
            xr.InteractionProfileSuggestedBinding(
                interaction_profile=xr.string_to_path(
                    self.instance, "/interaction_profiles/htc/vive_controller"
                ),
                suggested_bindings=[
                    xr.ActionSuggestedBinding(
                        self.left_pose_action,
                        xr.string_to_path(self.instance, "/user/hand/left/input/grip/pose"),
                    ),
                    xr.ActionSuggestedBinding(
                        self.right_pose_action,
                        xr.string_to_path(self.instance, "/user/hand/right/input/grip/pose"),
                    ),
                    xr.ActionSuggestedBinding(
                        self.left_trigger_action,
                        xr.string_to_path(self.instance, "/user/hand/left/input/trigger/value"),
                    ),
                    xr.ActionSuggestedBinding(
                        self.right_trigger_action,
                        xr.string_to_path(self.instance, "/user/hand/right/input/trigger/value"),
                    ),
                ],
            ),
        )

        self.left_space = xr.create_action_space(
            self.session, xr.ActionSpaceCreateInfo(action=self.left_pose_action)
        )
        self.right_space = xr.create_action_space(
            self.session, xr.ActionSpaceCreateInfo(action=self.right_pose_action)
        )
        self.view_space = xr.create_reference_space(
            self.session,
            xr.ReferenceSpaceCreateInfo(reference_space_type=xr.ReferenceSpaceType.VIEW),
        )

    def _pump_events(self) -> None:
        while True:
            try:
                event = xr.poll_event(self.instance)
                event_type = getattr(event, "type", None)

                if event_type == xr.StructureType.EVENT_DATA_SESSION_STATE_CHANGED or isinstance(
                    event, xr.EventDataSessionStateChanged
                ):
                    if not isinstance(event, xr.EventDataSessionStateChanged):
                        event = ctypes.cast(
                            ctypes.byref(event), ctypes.POINTER(xr.EventDataSessionStateChanged)
                        ).contents

                    self.session_state = event.state

                    if self.session_state == xr.SessionState.READY:
                        xr.begin_session(
                            self.session,
                            xr.SessionBeginInfo(xr.ViewConfigurationType.PRIMARY_STEREO),
                        )
                    elif self.session_state == xr.SessionState.STOPPING:
                        xr.end_session(self.session)
            except xr.EventUnavailable:
                break

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        self._frames_polled += 1
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.session:
            time.sleep(0.01)
            return frame

        self._pump_events()

        if self.session_state not in (
            xr.SessionState.VISIBLE,
            xr.SessionState.FOCUSED,
            xr.SessionState.SYNCHRONIZED,
        ):
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
            except xr.XrException as sync_err:
                # Controller input for this frame is stale; poses below may
                # still be valid, so the frame is worth keeping. Counted,
                # because a session where this fails constantly has trigger and
                # grip columns that are flat rather than genuinely unpressed.
                self.faults.record("action_sync", sync_err)

            # 1. HMD Evaluation
            if self.view_space:
                try:
                    view_loc = xr.locate_space(self.view_space, self.app_space, t)
                    if view_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                        frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = (
                            view_loc.pose.position.x,
                            view_loc.pose.position.y,
                            view_loc.pose.position.z,
                        )
                        frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = (
                            view_loc.pose.orientation.x,
                            view_loc.pose.orientation.y,
                            view_loc.pose.orientation.z,
                            view_loc.pose.orientation.w,
                        )
                        frame.hmd_tracking_valid = 1.0
                except xr.XrException as hmd_err:
                    self.faults.record("hmd", hmd_err)

            # 2. Controllers
            if self.left_space:
                try:
                    left_loc = xr.locate_space(self.left_space, self.app_space, t)
                    if left_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                        frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = (
                            left_loc.pose.position.x,
                            left_loc.pose.position.y,
                            left_loc.pose.position.z,
                        )
                        frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = (
                            left_loc.pose.orientation.x,
                            left_loc.pose.orientation.y,
                            left_loc.pose.orientation.z,
                            left_loc.pose.orientation.w,
                        )
                        frame.left_tracking_valid = 1.0

                        left_trig = xr.get_action_state_float(
                            self.session, xr.ActionStateGetInfo(action=self.left_trigger_action)
                        )
                        if left_trig.is_active:
                            frame.left_trigger = left_trig.current_state
                except xr.XrException as left_err:
                    self.faults.record("left_controller", left_err)

            if self.right_space:
                try:
                    right_loc = xr.locate_space(self.right_space, self.app_space, t)
                    if right_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                        frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = (
                            right_loc.pose.position.x,
                            right_loc.pose.position.y,
                            right_loc.pose.position.z,
                        )
                        (
                            frame.right_rot_x,
                            frame.right_rot_y,
                            frame.right_rot_z,
                            frame.right_rot_w,
                        ) = (
                            right_loc.pose.orientation.x,
                            right_loc.pose.orientation.y,
                            right_loc.pose.orientation.z,
                            right_loc.pose.orientation.w,
                        )
                        frame.right_tracking_valid = 1.0

                        right_trig = xr.get_action_state_float(
                            self.session, xr.ActionStateGetInfo(action=self.right_trigger_action)
                        )
                        if right_trig.is_active:
                            frame.right_trigger = right_trig.current_state
                except xr.XrException as right_err:
                    self.faults.record("right_controller", right_err)

            # 3. Eye Tracking Evaluation
            if self.eye_driver:
                try:
                    self.eye_driver.populate_frame(frame, t)
                except Exception as eye_err:  # noqa: BLE001 - vendor driver called through ctypes
                    # Broader than the clauses above on purpose. The eye drivers
                    # are vendor extensions reached through raw ctypes function
                    # pointers, and a bad pointer surfaces as OSError,
                    # ValueError or ArgumentError rather than as an XrException.
                    # Narrowing here would mean an eye-tracking fault killing the
                    # whole frame, including head and hand data that were fine.
                    self.faults.record("eye", eye_err)

        except xr.XrException as e:
            # The frame lifecycle itself -- wait_frame/begin_frame. Losing this
            # loses every source for this frame, so it is counted separately;
            # `frame` still returns with all its valid flags at 0.0 and the
            # engine drops it rather than recording zeros as data.
            self.faults.record("frame", e)

        finally:
            # We MUST end the frame to keep the session alive, but we can safely ignore the headless discard warning
            try:
                self.frame_end_info.display_time = t
                xr.end_frame(self.session, self.frame_end_info)
            except xr.XrException as end_err:
                if "discarded" not in str(end_err).lower():
                    self.faults.record("end_frame", end_err)

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

        # Before the "terminated" line, so the last thing in the session log is
        # not a clean shutdown message sitting on top of a session that lost
        # tracking for half its frames.
        self.faults.summarise(self._frames_polled)
        logger.info("OpenXR Context Safely Terminated.")

    def _query_refresh_rate(self, enabled_extensions: list) -> None:
        if "XR_FB_display_refresh_rate" not in enabled_extensions:
            return
        try:
            get_rate_fn = xr.get_instance_proc_addr(self.instance, "xrGetDisplayRefreshRateFB")
            if not get_rate_fn:
                return
            rate = ctypes.c_float()
            func = ctypes.CFUNCTYPE(xr.Result, xr.Session, ctypes.POINTER(ctypes.c_float))(
                get_rate_fn
            )
            res = func(self.session, ctypes.byref(rate))
            if not xr.Result(res).is_exception() and rate.value > 0:
                self.refresh_rate_hz = float(rate.value)
                logger.info(
                    f"Live HMD refresh rate reported by runtime: {self.refresh_rate_hz:.1f} Hz"
                )
        except Exception as e:  # noqa: BLE001 - one-off optional probe through a raw ctypes pointer
            # Called once at startup, through a function pointer resolved by
            # name from the runtime. Every failure mode -- extension absent,
            # symbol missing, signature mismatch -- means the same thing to the
            # caller: no live refresh rate, use the configured sampling cap.
            # _run_pcvr_mode already logs that fallback at WARNING.
            logger.debug(f"Refresh rate query failed (non-critical): {e}")

    def get_refresh_rate_hz(self) -> float | None:
        return self.refresh_rate_hz
