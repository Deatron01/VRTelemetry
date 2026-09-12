# tests/unit/test_av_recording_registry.py
"""Capture backend selection (mirrors test_backend_registry.py's coverage).

The property that matters most here is the same one src.backends.registry is
tested for: importing this module, and resolving names through it, must not
require ffmpeg, imageio-ffmpeg or faster-whisper to be installed. A/V
recording is off by default (``ConsentSettings.enable_av_recording``), and a
workstation that never turns it on must not pay an import cost for it.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from src.av_recording import registry
from src.core.exceptions import AVCaptureUnavailableError


def test_known_backends_lists_both_entries():
    assert registry.known_backends() == ("pc_compositor_mirror", "quest_on_device")


@pytest.mark.parametrize(
    ("telemetry_backend", "expected"),
    [
        ("openxr", "pc_compositor_mirror"),
        ("openxr_headless", "pc_compositor_mirror"),
        ("oculus", "pc_compositor_mirror"),
        ("steamvr", "pc_compositor_mirror"),
        ("quest_udp", "quest_on_device"),
    ],
)
def test_resolve_for_telemetry_backend_pairs_correctly(telemetry_backend, expected):
    assert registry.resolve_for_telemetry_backend(telemetry_backend) == expected


def test_resolve_for_telemetry_backend_is_none_for_an_unknown_name():
    assert registry.resolve_for_telemetry_backend("not-a-real-backend") is None


def test_an_unknown_capture_backend_name_is_refused_with_the_available_list():
    with pytest.raises(AVCaptureUnavailableError) as caught:
        registry.create_av_capture_backend("not-a-real-backend")

    message = str(caught.value)
    assert "not-a-real-backend" in message
    for name in registry.known_backends():
        assert name in message


def test_the_quest_backend_is_registered_but_not_implemented():
    """Constructs fine (it is importable with no native dependency); every
    method on it raises, per quest_capture.py's own docstring."""
    backend = registry.create_av_capture_backend("quest_on_device")
    with pytest.raises(AVCaptureUnavailableError):
        backend.start(Path("nowhere.mp4"))


def test_a_capture_backend_can_be_registered_by_name_rather_than_patched():
    constructed: list[str] = []

    class _FakeCapture:
        def __init__(self) -> None:
            constructed.append("built")

        def start(self, output_path):  # noqa: ARG002 - matching IAVCaptureBackend's signature
            raise AssertionError  # pragma: no cover - not called here

        def pause(self):  # pragma: no cover
            raise AssertionError

        def resume(self):  # pragma: no cover
            raise AssertionError

        def stop(self):  # pragma: no cover
            raise AssertionError

    module = types.ModuleType("tests_fake_av_capture_module")
    module.FakeCapture = _FakeCapture
    sys.modules["tests_fake_av_capture_module"] = module
    try:
        registry.register(
            registry.AVBackendEntry(
                name="fake",
                module="tests_fake_av_capture_module",
                attribute="FakeCapture",
                summary="a fake, for tests",
            )
        )
        assert "fake" in registry.known_backends()
        assert isinstance(registry.create_av_capture_backend("fake"), _FakeCapture)
        assert constructed == ["built"]
    finally:
        registry._REGISTRY.pop("fake", None)
        sys.modules.pop("tests_fake_av_capture_module", None)


def test_a_backend_whose_module_fails_to_import_names_why():
    """pc_compositor_mirror imports fine (no third-party import at module
    scope), but a backend whose module genuinely cannot be imported must say
    so rather than raising the raw ImportError past this layer."""

    registry.register(
        registry.AVBackendEntry(
            name="broken",
            module="tests_module_that_does_not_exist_at_all",
            attribute="Whatever",
            summary="deliberately broken, for this test",
        )
    )
    try:
        with pytest.raises(AVCaptureUnavailableError, match="broken"):
            registry.create_av_capture_backend("broken")
    finally:
        registry._REGISTRY.pop("broken", None)
