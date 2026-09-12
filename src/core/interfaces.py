# src/core/interfaces.py

from abc import ABC, abstractmethod
from pathlib import Path

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


class IAVCaptureBackend(ABC):
    """Capturing what the participant sees and hears during a session.

    A/V recording (speech recording, transcription & stress-inference project,
    Sep 2026) sits *beside* :class:`IVRBackend`, not inside it, and this is a
    second port rather than a method added to that one:

    * ``IVRBackend.poll_frame`` is called once per telemetry sample, up to
      120Hz, and returns immediately. A/V capture is a continuous background
      stream (video + microphone audio) with nothing that maps to "poll a
      frame" -- it is started once and runs until stopped.
    * A machine with no VR bindings must still be able to import the
      acquisition code (``tests/unit/test_no_import_time_io.py`` and the
      backend registry's own tests exist for exactly this). The same has to
      hold for capture backends: resolved by name through
      ``src.av_recording.registry``, exactly like ``src.backends.registry``
      resolves an :class:`IVRBackend`, so that a machine with no capture
      dependencies installed can still import the recording pipeline.

    Implementations: ``PCCompositorMirrorCapture`` (the runtime's mirror
    window + microphone, for the ``openxr``/``oculus``/``steamvr`` backends)
    and ``QuestOnDeviceCapture`` (Android ``MediaProjection``, for
    ``quest_udp`` standalone sessions -- not implemented in this repository;
    see ``src/av_recording/quest_capture.py``).
    """

    @abstractmethod
    def start(self, output_path: Path) -> None:
        """Begin capturing towards ``output_path`` (the final muxed video).

        Must not block on participant activity: it starts capture
        infrastructure (a subprocess, a platform capture session) and returns.
        The file at ``output_path`` need not exist yet when this returns --
        only when :meth:`stop` returns.

        Raises:
            AVCaptureUnavailableError: this backend cannot capture on this
                machine right now (no mirror window found, no audio device
                bound, the capture subprocess failed to launch).
        """

    @abstractmethod
    def pause(self) -> None:
        """Stop writing captured frames until :meth:`resume`.

        What a participant's "Pause recording" control does (Consent Texts
        addendum, Section 3.3) -- independent of stopping the session outright,
        and logged by the caller as a pause event, not by the backend. Capture
        infrastructure may be torn down and rebuilt on resume; pausing is
        defined by its effect on the recorded output, not by how a given
        backend implements it.

        Calling this while already paused is a no-op.
        """

    @abstractmethod
    def resume(self) -> None:
        """Resume capturing after :meth:`pause`. A no-op if not paused."""

    @abstractmethod
    def stop(self) -> Path:
        """Finish capturing and return the path to the final output file.

        Returns:
            The muxed video file at the ``output_path`` given to
            :meth:`start`. Must exist and be non-empty when this returns -- a
            backend that cannot guarantee that raises instead of returning a
            path nothing wrote.

        Raises:
            AVCaptureUnavailableError: capture failed and no usable output
                exists.
        """
