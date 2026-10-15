# src/backends/openxr_headless.py

import ctypes
import logging
import platform
import time

import xr

from src.backends.desktop_mirror import DesktopMirrorLayer
from src.backends.tracking_faults import TrackingFaultLog
from src.config import get_settings
from src.core.datatypes import TelemetryFrame
from src.core.exceptions import HardwareBindingError
from src.core.interfaces import IVRBackend
from src.eye_tracking.base_driver import IEyeTrackingDriver
from src.eye_tracking.factory import EyeTrackingFactory

logger = logging.getLogger(__name__)


class OpenXRHeadlessBackend(IVRBackend):
    """
    Headless OpenXR backend abstraction. Attempts pure XR_MND_headless execution.
    If running on proprietary runtimes (Meta/Oculus, SteamVR) that lack this extension,
    it falls back to an invisible Direct3D 11 device context to run silently in the background
    without requiring an active window (resolves Oculus OpenGL compatibility drops).
    """

    #: OpenXR stamps frames with `predicted_display_time`.
    timestamp_is_display_time = True

    def __init__(self) -> None:
        self.instance: xr.Instance | None = None
        self.system_id: xr.SystemId | None = None
        self.session: xr.Session | None = None
        self.app_space: xr.Space | None = None

        self.action_set: xr.ActionSet | None = None
        self.left_pose_action: xr.Action | None = None
        self.right_pose_action: xr.Action | None = None
        self.left_trigger_action: xr.Action | None = None
        self.right_trigger_action: xr.Action | None = None

        self.left_space: xr.Space | None = None
        self.right_space: xr.Space | None = None
        self.eye_driver: IEyeTrackingDriver | None = None

        # Annotated rather than left as bare `None`: these hold ctypes handles
        # from `_create_d3d11_binding()`, and an attribute the checker believes
        # is permanently None makes every later `byref`/`cast` on it an error it
        # cannot distinguish from a real one (VRT-17).
        self.graphics_binding: xr.GraphicsBindingD3D11KHR | None = None
        self.d3d_device: ctypes.c_void_p | None = None
        self.d3d_context: ctypes.c_void_p | None = None
        self.is_pure_headless = False
        self.session_state = xr.SessionState.UNKNOWN

        self.active_action_set_info = xr.ActiveActionSet()
        self.actions_sync_info = xr.ActionsSyncInfo()
        self.view_locate_info = xr.ViewLocateInfo(
            view_configuration_type=xr.ViewConfigurationType.PRIMARY_STEREO
        )
        self.frame_end_info = xr.FrameEndInfo(environment_blend_mode=xr.EnvironmentBlendMode.OPAQUE)

        #: Per-source tracking faults (VRT-13). See
        #: :mod:`src.backends.tracking_faults`.
        self.faults = TrackingFaultLog("OpenXRHeadlessBackend")
        self._frames_polled = 0

        #: Desktop mirror layer for feeding the SteamVR compositor window.
        #: ``None`` on pure-headless or when the feature is disabled / failed.
        self.desktop_mirror: DesktopMirrorLayer | None = None
        self.supports_cylinder_layer = False

    def _create_d3d11_binding(self) -> None:
        """Constructs an invisible D3D11 graphics device to satisfy Windows XR runtimes."""
        if platform.system() != "Windows":
            raise NotImplementedError("D3D11 fallback is only supported on Windows.")

        try:
            # OpenXR requires querying graphics requirements before session creation
            reqs = xr.get_d3d11_graphics_requirements_khr(self.instance, self.system_id)
            logger.debug(f"D3D11 Graphics Requirements: min_feature_level={reqs.min_feature_level}")

            # Load the D3D11 DLL via ctypes
            # Windows-only by construction -- the guard above returns on every
            # other platform -- but `ctypes.windll` does not exist for a type
            # checker running on Linux, which is where CI runs.
            d3d11 = ctypes.windll.d3d11  # type: ignore[attr-defined]

            D3D_DRIVER_TYPE_HARDWARE = 1
            D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20
            D3D11_SDK_VERSION = 7

            self.d3d_device = ctypes.c_void_p()
            self.d3d_context = ctypes.c_void_p()
            feature_level = ctypes.c_uint()

            # HRESULT WINAPI D3D11CreateDevice(...)
            res = d3d11.D3D11CreateDevice(
                None,  # pAdapter (Use default)
                D3D_DRIVER_TYPE_HARDWARE,  # DriverType
                None,  # Software
                D3D11_CREATE_DEVICE_BGRA_SUPPORT,  # Flags
                None,  # pFeatureLevels
                0,  # FeatureLevels count
                D3D11_SDK_VERSION,  # SDKVersion
                ctypes.byref(self.d3d_device),
                ctypes.byref(feature_level),
                ctypes.byref(self.d3d_context),
            )

            if res != 0:
                raise RuntimeError(
                    f"D3D11CreateDevice failed with HRESULT: {hex(res & 0xFFFFFFFF)}"
                )

            # Bind the raw device pointer to OpenXR
            self.graphics_binding = xr.GraphicsBindingD3D11KHR(
                device=ctypes.cast(self.d3d_device, ctypes.c_void_p)
            )
            logger.info("D3D11 dummy graphics binding created successfully.")

        except Exception as e:
            logger.error(f"Failed to create D3D11 graphics binding: {e}")
            raise

    def initialize(self) -> bool:
        try:
            available_extensions: list[str] = [
                ext.extension_name.decode("utf-8")
                if isinstance(ext.extension_name, bytes)
                else ext.extension_name
                for ext in xr.enumerate_instance_extension_properties()
            ]
            enabled_extensions: list[str] = []

            if "XR_MND_headless" in available_extensions:
                enabled_extensions.append("XR_MND_headless")
                self.is_pure_headless = True
                logger.info("Native Headless extension detected.")
            else:
                logger.warning(
                    "XR_MND_headless missing. Falling back to D3D11 dummy context (Oculus/SteamVR Mode)."
                )
                if "XR_KHR_D3D11_enable" in available_extensions:
                    enabled_extensions.append("XR_KHR_D3D11_enable")
                else:
                    logger.error("Neither Headless nor D3D11 extensions are supported. Aborting.")
                    return False

            if "XR_KHR_composition_layer_cylinder" in available_extensions:
                enabled_extensions.append("XR_KHR_composition_layer_cylinder")
                self.supports_cylinder_layer = True
            else:
                self.supports_cylinder_layer = False

            self.eye_driver = EyeTrackingFactory.create_best_driver(available_extensions)
            if self.eye_driver:
                driver_ext = self.eye_driver.get_extension_name()
                if driver_ext and driver_ext in available_extensions:
                    enabled_extensions.append(driver_ext)
                for req_ext in self.eye_driver.get_additional_extensions():
                    if req_ext in available_extensions:
                        enabled_extensions.append(req_ext)

            self.instance = xr.create_instance(
                create_info=xr.InstanceCreateInfo(
                    application_info=xr.ApplicationInfo(
                        application_name="VRTelemetry_Background", api_version=xr.Version(1, 0, 0)
                    ),
                    enabled_extension_names=enabled_extensions,
                )
            )

            self.system_id = xr.get_system(
                self.instance, xr.SystemGetInfo(xr.FormFactor.HEAD_MOUNTED_DISPLAY)
            )

            if not self.is_pure_headless:
                self._create_d3d11_binding()
                binding = self.graphics_binding
                if binding is None:  # pragma: no cover - _create_d3d11_binding raises instead
                    raise HardwareBindingError(
                        "D3D11 graphics binding was not created; cannot open a session."
                    )
                session_create_info = xr.SessionCreateInfo(
                    system_id=self.system_id,
                    next=ctypes.cast(ctypes.pointer(binding), ctypes.c_void_p),
                )
            else:
                session_create_info = xr.SessionCreateInfo(system_id=self.system_id)

            self.session = xr.create_session(self.instance, session_create_info)

            try:
                self.app_space = xr.create_reference_space(
                    self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.LOCAL)
                )
            except xr.XrException as local_err:
                # Fall back to STAGE when the runtime offers no LOCAL space.
                # Narrowed to the runtime's own exception so a fault in our own
                # call is not retried as if it were a missing capability; if
                # STAGE fails too, initialize()'s handler reports the bind
                # failure rather than this branch hiding it.
                logger.info(
                    f"LOCAL reference space unavailable, falling back to STAGE: {local_err}"
                )
                self.app_space = xr.create_reference_space(
                    self.session, xr.ReferenceSpaceCreateInfo(xr.ReferenceSpaceType.STAGE)
                )

            self._setup_actions()

            if self.eye_driver:
                self.eye_driver.initialize(self.instance, self.session, self.app_space)

            # --- AGGREGATE ACTION SETS FOR SINGLE-PASS ATTACHMENT ---
            action_sets_to_attach = [self.action_set]

            self.active_action_set_info.action_set = self.action_set
            self.active_action_set_info.subaction_path = xr.NULL_PATH
            active_sets_for_sync = [self.active_action_set_info]

            # Bind the eye driver's action set if it published one.
            # `getattr(..., None)` until VRT-17, because IEyeTrackingDriver did
            # not declare the attribute; it is part of the interface now.
            eye_action_set = self.eye_driver.gaze_action_set if self.eye_driver else None
            if eye_action_set is not None:
                action_sets_to_attach.append(eye_action_set)

                gaze_set_info = xr.ActiveActionSet()
                gaze_set_info.action_set = eye_action_set
                gaze_set_info.subaction_path = xr.NULL_PATH
                active_sets_for_sync.append(gaze_set_info)

            # Attach combined array to fulfill spec requirements
            xr.attach_session_action_sets(
                self.session, xr.SessionActionSetsAttachInfo(action_sets=action_sets_to_attach)
            )

            # Map aggregated set data back to the core frame sync state
            self.actions_sync_info.active_action_sets = active_sets_for_sync

            self.view_locate_info.space = self.app_space

            # --- DESKTOP MIRROR LAYER (SteamVR compositor feed) ---
            # Only when we own a D3D11 device (non-pure-headless) and the
            # config allows it. A failure here is non-fatal: the recording
            # proceeds normally, but the SteamVR mirror window stays black.
            if (
                not self.is_pure_headless
                and self.d3d_device
                and self.d3d_context
                and get_settings().acquisition.enable_desktop_mirror
            ):
                try:
                    mirror = DesktopMirrorLayer()
                    mirror.setup(
                        session=self.session,
                        d3d_device=self.d3d_device,
                        d3d_context=self.d3d_context,
                        space=self.app_space,
                        use_cylinder=self.supports_cylinder_layer,
                    )
                    self.desktop_mirror = mirror
                except Exception:  # optional feature, never blocks recording
                    logger.warning(
                        "Desktop mirror unavailable; compositor window will stay black.",
                        exc_info=True,
                    )

            logger.info("OpenXR telemetry context established successfully.")
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
                    self.instance, "/interaction_profiles/oculus/touch_controller"
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

    def _pump_events(self) -> None:
        while True:
            try:
                event_buffer = xr.poll_event(self.instance)
            except xr.exception.EventUnavailable:
                # Not an error: this is how OpenXR signals "no event queued
                # right now". pyopenxr's poll_event never returns None (it
                # always returns an EventDataBuffer or raises), so this is the
                # only way to end the pump loop each frame -- the old
                # `if event is None: break` never actually fired, and left
                # this exception unhandled, crashing the main loop on the
                # very first poll of every session.
                break
            if event_buffer.type != xr.StructureType.EVENT_DATA_SESSION_STATE_CHANGED:
                continue
            # EventDataBuffer is a plain fixed-size ctypes buffer, unrelated
            # by inheritance to EventDataSessionStateChanged, so
            # `isinstance(event_buffer, xr.EventDataSessionStateChanged)`
            # (the old check) can never be True. It must be reinterpreted via
            # its `type` field instead, with the same ctypes.cast pattern
            # __init__ already uses elsewhere in this class.
            event = ctypes.cast(
                ctypes.byref(event_buffer), ctypes.POINTER(xr.EventDataSessionStateChanged)
            ).contents
            self.session_state = xr.SessionState(event.state)
            logger.info(f"OpenXR Headless Session State Transitioned to: {self.session_state}")
            if self.session_state == xr.SessionState.READY:
                xr.begin_session(
                    self.session, xr.SessionBeginInfo(xr.ViewConfigurationType.PRIMARY_STEREO)
                )
            elif self.session_state == xr.SessionState.STOPPING:
                xr.end_session(self.session)

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        self._frames_polled += 1
        frame = TelemetryFrame.create_empty(frame_index)
        if not self.session:
            return frame

        self._pump_events()

        # Ensure the session has started tracking before waiting for frames
        if self.session_state not in (
            xr.SessionState.VISIBLE,
            xr.SessionState.FOCUSED,
            xr.SessionState.SYNCHRONIZED,
        ):
            return frame

        # A pure headless session has no display, so the runtime has no display
        # time to predict: xr.wait_frame() succeeds and returns
        # predicted_display_time == 0 (verified against this project's HTC
        # runtime, which is the only kind of session this backend ever opens).
        # Passing that zero on as the XrTime argument to locate_views /
        # locate_space below is what raised
        # "TimeInvalidError: The provided basetype:XrTime was zero, negative, or
        # out of range" on every single frame -- 100% frame faults and zero rows
        # written, on every openxr_headless recording. backend_openxr already
        # guards exactly this ("in case the runtime refuses to predict one");
        # this backend, the one that is *always* headless and so always hits it,
        # did not. perf_counter_ns() is what that sibling falls back to, and the
        # runtime accepts it: locate_space and locate_views both return
        # view_state_flags 15 (position and orientation valid *and* tracked).
        t = time.perf_counter_ns()

        try:
            state = xr.wait_frame(self.session)
            xr.begin_frame(self.session)
            if state.predicted_display_time > 0:
                t = state.predicted_display_time
            frame.timestamp_ns = t

            xr.sync_actions(self.session, self.actions_sync_info)

            # 1. HMD Spatial Transforms (Gives you real head positions)
            self.view_locate_info.view_configuration_type = xr.ViewConfigurationType.PRIMARY_STEREO
            self.view_locate_info.display_time = t
            v_state, views = xr.locate_views(self.session, self.view_locate_info)

            if len(views) > 0 and (v_state.view_state_flags & xr.VIEW_STATE_POSITION_VALID_BIT):
                pos, rot = views[0].pose.position, views[0].pose.orientation
                frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z = pos.x, pos.y, pos.z
                frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w = (
                    rot.x,
                    rot.y,
                    rot.z,
                    rot.w,
                )
                frame.hmd_tracking_valid = 1.0

            # 2. Controller Spatials
            l_loc = xr.locate_space(self.left_space, self.app_space, t)
            if l_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                pos, rot = l_loc.pose.position, l_loc.pose.orientation
                frame.left_pos_x, frame.left_pos_y, frame.left_pos_z = pos.x, pos.y, pos.z
                frame.left_rot_x, frame.left_rot_y, frame.left_rot_z, frame.left_rot_w = (
                    rot.x,
                    rot.y,
                    rot.z,
                    rot.w,
                )
                frame.left_tracking_valid = 1.0

            r_loc = xr.locate_space(self.right_space, self.app_space, t)
            if r_loc.location_flags & xr.SPACE_LOCATION_POSITION_VALID_BIT:
                pos, rot = r_loc.pose.position, r_loc.pose.orientation
                frame.right_pos_x, frame.right_pos_y, frame.right_pos_z = pos.x, pos.y, pos.z
                frame.right_rot_x, frame.right_rot_y, frame.right_rot_z, frame.right_rot_w = (
                    rot.x,
                    rot.y,
                    rot.z,
                    rot.w,
                )
                frame.right_tracking_valid = 1.0

            # 3. Inputs & Biometrics
            l_trig = xr.get_action_state_float(
                self.session, xr.ActionStateGetInfo(action=self.left_trigger_action)
            )
            r_trig = xr.get_action_state_float(
                self.session, xr.ActionStateGetInfo(action=self.right_trigger_action)
            )
            frame.left_trigger = l_trig.current_state if l_trig.is_active else 0.0
            frame.right_trigger = r_trig.current_state if r_trig.is_active else 0.0

            if self.eye_driver:
                self.eye_driver.populate_frame(frame, t)

            # 4. Submit frame — with desktop mirror layer if available
            self.frame_end_info.display_time = t
            if self.desktop_mirror:
                quad = self.desktop_mirror.update_and_get_layer()
                if quad is not None:
                    layer_ptr = ctypes.cast(
                        ctypes.pointer(quad),
                        ctypes.POINTER(xr.CompositionLayerBaseHeader),
                    )
                    layer_arr = (ctypes.POINTER(xr.CompositionLayerBaseHeader) * 1)(layer_ptr)
                    self.frame_end_info.layer_count = 1
                    self.frame_end_info.layers = ctypes.cast(
                        layer_arr,
                        ctypes.POINTER(ctypes.POINTER(xr.CompositionLayerBaseHeader)),
                    )
                else:
                    self.frame_end_info.layer_count = 0
                    self.frame_end_info.layers = None
            xr.end_frame(self.session, self.frame_end_info)

        except xr.XrException as e:
            # Whole-frame fault. Counted rather than only logged: "visible" was
            # already the intent of the line this replaces, but one ERROR per
            # dropped frame at 120 Hz is not visibility, it is a log nobody can
            # read. The tally lands in the shutdown summary instead, next to the
            # frame count it needs to be read against.
            self.faults.record("frame", e)

        return frame

    def shutdown(self) -> None:
        """Release every OpenXR handle this backend owns, exactly once.

        Each handle is cleared as it is destroyed, which is what makes a
        second call a no-op instead of a double-destroy. That matters because
        there are two callers -- ``initialize()``'s own failure path and the
        engine's teardown -- and a backend whose init failed halfway gets
        both. Handing an already-destroyed handle back to the runtime is an
        access violation, not a Python exception, so no handler can clean up
        after it; it simply must not happen. ``backend_openxr``,
        ``backend_ocolus`` and ``backend_steamvr`` all clear as they go for
        this reason. This one did not, which is the bug.
        """
        released = any(
            (
                self.eye_driver,
                self.desktop_mirror,
                self.left_space,
                self.right_space,
                self.app_space,
                self.action_set,
                self.session,
                self.instance,
            )
        )

        if self.eye_driver:
            self.eye_driver.shutdown()
            self.eye_driver = None
        # Desktop mirror owns a swapchain under this session — destroy it
        # before the session itself.
        if self.desktop_mirror:
            self.desktop_mirror.destroy()
            self.desktop_mirror = None
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

        self.session_state = xr.SessionState.UNKNOWN

        # Clean D3D11 resources from memory
        self.graphics_binding = None
        if self.d3d_device:
            self.d3d_device = None
            self.d3d_context = None

        # Only on the call that actually released something: a repeat call is
        # silent rather than logging a second, duplicate fault summary.
        if released:
            self.faults.summarise(self._frames_polled)
            logger.info("OpenXR Context Safely Terminated.")
