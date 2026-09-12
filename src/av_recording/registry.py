# src/av_recording/registry.py
"""Which A/V capture backend to use, resolved by name (mirrors src.backends.registry).

Two implementations exist, named by the *telemetry* backend they run
alongside rather than by platform, because that is the axis that actually
decides where the video comes from:

* ``pc_compositor_mirror`` -- the runtime's mirror window on the PC, for the
  ``openxr`` / ``oculus`` / ``steamvr`` telemetry backends.
* ``quest_on_device`` -- Android ``MediaProjection`` on the headset itself,
  for the ``quest_udp`` telemetry backend. **Not implemented in this
  repository**; see ``quest_capture.py`` for why capturing on an Android
  process cannot be code that lives in ``src/``.

Imports the chosen backend and only that one, for the same reason
``src.backends.registry`` does: importing ``src.av_recording`` on a machine
with no ffmpeg installed must not fail, and a session recorder must be able to
ask "is anything available?" without paying for every backend's import.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from src.core.exceptions import AVCaptureUnavailableError
from src.core.interfaces import IAVCaptureBackend


@dataclass(frozen=True)
class AVBackendEntry:
    """One selectable capture backend. See ``src.backends.registry.BackendEntry``."""

    name: str
    module: str
    attribute: str
    summary: str


#: The telemetry backend name each capture backend is meant to run alongside.
#: Not enforced here -- ``SessionRecorder`` decides whether to attempt capture
#: at all -- but it is what a caller resolving "the right capture backend for
#: this telemetry backend" should key off.
TELEMETRY_BACKEND_TO_CAPTURE_BACKEND: dict[str, str] = {
    "openxr": "pc_compositor_mirror",
    "openxr_headless": "pc_compositor_mirror",
    "oculus": "pc_compositor_mirror",
    "steamvr": "pc_compositor_mirror",
    "quest_udp": "quest_on_device",
}

_REGISTRY: dict[str, AVBackendEntry] = {
    "pc_compositor_mirror": AVBackendEntry(
        name="pc_compositor_mirror",
        module="src.av_recording.pc_compositor_capture",
        attribute="PCCompositorMirrorCapture",
        summary="ffmpeg gdigrab of the runtime's compositor mirror window + microphone (dshow)",
    ),
    "quest_on_device": AVBackendEntry(
        name="quest_on_device",
        module="src.av_recording.quest_capture",
        attribute="QuestOnDeviceCapture",
        summary=(
            "Android MediaProjection on the Quest itself -- not implemented in this "
            "repository, see quest_capture.py"
        ),
    ),
}


def known_backends() -> tuple[str, ...]:
    """Every registered name, sorted. Does not import anything."""
    return tuple(sorted(_REGISTRY))


def register(entry: AVBackendEntry) -> None:
    """Add or replace a capture backend. For tests and out-of-tree backends."""
    _REGISTRY[entry.name] = entry


def resolve_for_telemetry_backend(telemetry_backend: str) -> str | None:
    """Which capture backend, if any, pairs with a given telemetry backend name."""
    return TELEMETRY_BACKEND_TO_CAPTURE_BACKEND.get(telemetry_backend)


def create_av_capture_backend(name: str) -> IAVCaptureBackend:
    """Import and construct the capture backend called ``name``.

    Args:
        name: A key of :func:`known_backends`.

    Returns:
        A constructed, unstarted backend.

    Raises:
        AVCaptureUnavailableError: ``name`` is unknown, or the module failed
            to import (missing ffmpeg/imageio-ffmpeg, on this backend).
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        options = ", ".join(known_backends())
        raise AVCaptureUnavailableError(
            f"Unknown A/V capture backend {name!r}. Available: {options}."
        )
    try:
        module = import_module(entry.module)
    except ImportError as exc:
        raise AVCaptureUnavailableError(
            f"The {entry.name!r} A/V capture backend ({entry.summary}) is not available on "
            f"this machine: {exc}."
        ) from exc

    backend_class: type[IAVCaptureBackend] = getattr(module, entry.attribute)
    return backend_class()
