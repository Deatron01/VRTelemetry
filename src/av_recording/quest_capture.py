# src/av_recording/quest_capture.py
"""Quest standalone on-device A/V capture -- not implemented in this repository.

The ``quest_udp`` telemetry backend runs on an Android process on the headset
itself (see ``src/backends/udp_receiver.py`` -- it is not an ``IVRBackend`` at
all, it is a socket the engine listens on). Capturing what that process shows
and plays is therefore Android ``MediaProjection`` (screen/compositor capture)
+ ``AudioPlaybackCaptureConfiguration`` + the microphone, running as part of
the Quest app itself and uploading its own output -- code that has to live in
the Android project's source tree, which this repository does not contain
(``apk/`` here holds build output, not app source).

This class exists so :mod:`src.av_recording.registry` has something to name
and fail informatively on, exactly the way ``backend_ocolus.py`` guards
``import ovr`` rather than omitting the Oculus backend from the registry
entirely: a researcher selecting ``quest_udp`` who also has A/V recording
switched on gets a clear "not available for this backend" rather than an
``AttributeError`` from a registry lookup that found nothing.
"""

from __future__ import annotations

from pathlib import Path

from src.core.exceptions import AVCaptureUnavailableError
from src.core.interfaces import IAVCaptureBackend


class QuestOnDeviceCapture(IAVCaptureBackend):
    """Placeholder. Every method raises; see the module docstring."""

    _NOT_IMPLEMENTED = (
        "On-device A/V capture for standalone Quest sessions is not implemented in this "
        "repository -- it requires Android MediaProjection code in the Quest app's own "
        "source tree, not the Python workstation backend. Record through openxr/oculus/"
        "steamvr for A/V capture, or implement the Android side of this before enabling "
        "A/V recording for quest_udp sessions."
    )

    def start(self, output_path: Path) -> None:  # noqa: ARG002 - signature fixed by IAVCaptureBackend
        raise AVCaptureUnavailableError(self._NOT_IMPLEMENTED)

    def pause(self) -> None:
        raise AVCaptureUnavailableError(self._NOT_IMPLEMENTED)

    def resume(self) -> None:
        raise AVCaptureUnavailableError(self._NOT_IMPLEMENTED)

    def stop(self) -> Path:
        raise AVCaptureUnavailableError(self._NOT_IMPLEMENTED)
