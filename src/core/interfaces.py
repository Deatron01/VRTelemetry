# src/core/interfaces.py

from abc import ABC, abstractmethod

from src.core.datatypes import TelemetryFrame


class IVRBackend(ABC):
    """
    Abstract Hardware Abstraction Layer (HAL) interface enforcing standard data access
    contracts across dynamic runtime backends.
    """

    #: Whether ``TelemetryFrame.timestamp_ns`` is the VR runtime's *display*
    #: time, rather than a local clock read at the moment we happened to ask.
    #:
    #: It decides whether the application's frame rate can be derived at all.
    #: OpenXR reports ``predicted_display_time``, which advances once per
    #: rendered frame, so consecutive values give the app's real cadence.
    #: SteamVR's overlay path stamps ``time.perf_counter_ns()`` when the pose is
    #: read -- a monotonic local clock with an arbitrary epoch, unrelated to the
    #: display. Dividing 1 by the gap between two of those gives the rate this
    #: process polled at, which is not a property of the application at all.
    #:
    #: The engine wrote exactly that into the ``app_fps`` column of every frame
    #: (VRT-24). False here means the column stays at its ``create_empty``
    #: default rather than carrying a fabricated number.
    timestamp_is_display_time: bool = False

    @abstractmethod
    def initialize(self) -> bool:
        """
        Establishes connections to runtime contexts and binds spatial interaction profiles.
        Must execute without spawning visible desktop windows.

        Returns:
            bool: True if context successfully bound, False otherwise.
        """
        pass

    @abstractmethod
    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        """
        Synchronously fetches the latest transform vectors and analog inputs from the active runtime.
        Expected to block execution tightly against the hardware's vsync/display timer.

        Args:
            frame_index (int): The current sequential index of the telemetry loop.

        Returns:
            TelemetryFrame: A populated 1D data class representing the exact hardware state.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Releases all open API handles, destroys spaces, and cleanly terminates
        the active runtime session.
        """
        pass
