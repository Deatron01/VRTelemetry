# src/eye_tracking/base_driver.py

from abc import ABC, abstractmethod

import xr

from src.core.datatypes import TelemetryFrame


class IEyeTrackingDriver(ABC):
    """
    Vendor-agnostic hardware abstraction contract. Decouples the proprietary mapping
    of OpenXR extensions from the internal data model generation.

    **The session belongs to the backend, not to the driver** (VRT-17).

    A driver may create action sets, actions and spaces. It must never call
    ``xr.attach_session_action_sets`` or ``xr.sync_actions``: both are
    session-wide, the backend owns the session, and only the backend knows the
    full set of actions to attach. A driver that needs an action set attached
    publishes it as :attr:`gaze_action_set` and the backend attaches and syncs
    it alongside its own.

    This is written down because it was previously tribal knowledge that two of
    the three drivers happened to follow. ``XR_EXT_eye_gaze_interaction``
    attached its own action set inside ``initialize()``, and
    ``xrAttachSessionActionSets`` may be called **at most once per session** --
    so the backend's own attach, which runs afterwards, failed with
    ``XR_ERROR_ACTIONSETS_ALREADY_ATTACHED``, ``initialize()`` returned False,
    and the OpenXR backend could not bind at all. On any headset exposing only
    the cross-vendor Khronos extension -- no Meta social eye tracking, no HTC
    facial tracking -- recording was impossible. `tests/unit/test_eye_tracking_contract.py`
    now fails the build if a driver reaches for either call.
    """

    #: The action set this driver needs attached to the session, or ``None`` if
    #: it does not use one (an extension-handle driver such as
    #: ``XR_FB_eye_tracking_social`` does not). Read by the backend during
    #: ``initialize()``; declared here so reading it is not a ``getattr`` against
    #: an interface that never mentioned it.
    gaze_action_set: "xr.ActionSet | None" = None

    @abstractmethod
    def get_extension_name(self) -> str:
        """
        Returns the primary OpenXR extension identifier required by this driver.
        """
        pass

    @abstractmethod
    def get_additional_extensions(self) -> list[str]:
        """
        Returns an array of supplemental OpenXR extensions required for full capability.
        """
        pass

    @abstractmethod
    def get_priority(self) -> int:
        """
        Resolution priority (higher indicates stronger biometric fidelity/accuracy).
        """
        pass

    @abstractmethod
    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        """
        Binds the internal OpenXR action mappings to the active headless session contexts.
        """
        pass

    @abstractmethod
    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        """
        Extracts real-time eye vectors, pupil dilations, and convergence data, directly
        mutating the supplied float32 TelemetryFrame tensor slice.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Discards active bindings and frees local resources.
        """
        pass
