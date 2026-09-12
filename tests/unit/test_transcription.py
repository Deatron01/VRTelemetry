# tests/unit/test_transcription.py
"""WhisperTranscriber's device fallback and error handling.

The fallback exists because of a real failure reproduced on VRT's own test
machine: faster-whisper's ``device="auto"`` detects a GPU at model
construction but does not verify the CUDA/cuBLAS/cuDNN runtime underneath
actually works, so construction succeeds and the very first ``.transcribe()``
call fails with a missing-DLL RuntimeError on any workstation with a GPU but
no CUDA toolkit installed -- an ordinary state for a researcher's machine.
Confirmed end-to-end against a real spoken .wav (Windows SAPI TTS) on that
machine: without the fallback, transcription was unavailable outright; with
it, the CPU retry produced a correct transcript.

No real faster-whisper model is loaded here (that would need real weights
downloaded) -- ``sys.modules["faster_whisper"]`` is replaced with a fake
module for every test, matching how test_av_recording_registry.py's
docstring states a CI machine need not have ffmpeg or faster-whisper
installed to run these tests at all.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.av_recording.transcription import TranscriptionUnavailableError, WhisperTranscriber


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeInfo:
    def __init__(self, language: str | None) -> None:
        self.language = language


def _install_fake_faster_whisper(
    monkeypatch: pytest.MonkeyPatch, transcribe_effects: list[Callable[[], Any]]
) -> list[str]:
    """Replaces the ``faster_whisper`` module with a fake whose
    ``WhisperModel.transcribe`` calls consume `transcribe_effects` in order
    -- each is a zero-arg callable that either returns
    ``(segments_iterable, info)`` or raises. Returns the list of `device=`
    values every constructed model was built with, in order."""
    devices_used: list[str] = []

    class _FakeWhisperModel:
        def __init__(self, model_size: str, device: str, compute_type: str) -> None:
            self.model_size = model_size
            self.device = device
            self.compute_type = compute_type
            devices_used.append(device)

        def transcribe(
            self,
            media_path: str,  # noqa: ARG002 - matching faster_whisper's real signature
            language: str | None = None,  # noqa: ARG002 - matching faster_whisper's real signature
        ) -> Any:
            return transcribe_effects.pop(0)()

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    return devices_used


_CUBLAS_ERROR = RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")


def test_a_normal_transcription_uses_the_gpu_device_and_returns_segments(monkeypatch):
    devices_used = _install_fake_faster_whisper(
        monkeypatch,
        [lambda: ([_FakeSegment(0.0, 1.5, " hello there")], _FakeInfo("en"))],
    )
    transcriber = WhisperTranscriber(model_size="base")

    transcript = transcriber.transcribe(Path("session.mp4"))

    assert devices_used == ["auto"]
    assert transcript.engine == "faster-whisper:base"
    assert transcript.language == "en"
    assert transcript.full_text == "hello there"


def test_a_gpu_runtime_failure_retries_once_on_cpu_and_succeeds(monkeypatch):
    devices_used = _install_fake_faster_whisper(
        monkeypatch,
        [
            lambda: (_ for _ in ()).throw(_CUBLAS_ERROR),
            lambda: ([_FakeSegment(0.0, 1.0, " ok")], _FakeInfo("en")),
        ],
    )
    transcriber = WhisperTranscriber(model_size="base")

    transcript = transcriber.transcribe(Path("session.mp4"))

    assert devices_used == ["auto", "cpu"]
    assert transcript.full_text == "ok"
    # The transcriber must remember the demotion rather than re-probing GPU
    # (and re-failing) on every subsequent call.
    assert transcriber._device == "cpu"


def test_after_falling_back_the_cpu_model_is_reused_not_rebuilt(monkeypatch):
    """_load_model caches self._model, so the CPU model built during the
    fallback must be reused on a later call -- not silently reconstructed
    (which would repeat the (relatively slow) model-load cost) and not
    reset back to probing GPU again."""
    devices_used = _install_fake_faster_whisper(
        monkeypatch,
        [
            lambda: (_ for _ in ()).throw(_CUBLAS_ERROR),
            lambda: ([_FakeSegment(0.0, 1.0, " first")], _FakeInfo("en")),
            lambda: ([_FakeSegment(0.0, 1.0, " second")], _FakeInfo("en")),
        ],
    )
    transcriber = WhisperTranscriber(model_size="base")

    transcriber.transcribe(Path("a.mp4"))
    transcript_two = transcriber.transcribe(Path("b.mp4"))

    # One construction each for the failed GPU attempt and the CPU fallback
    # -- not a third, since the now-working CPU model is cached and reused.
    assert devices_used == ["auto", "cpu"]
    assert transcript_two.full_text == "second"


def test_a_genuine_media_failure_is_not_mistaken_for_a_gpu_problem(monkeypatch):
    """A real decoding failure must surface as TranscriptionUnavailableError,
    not be swallowed by a retry-on-CPU that only makes sense for a
    GPU/CUDA-runtime error."""
    devices_used = _install_fake_faster_whisper(
        monkeypatch,
        [lambda: (_ for _ in ()).throw(ValueError("moov atom not found"))],
    )
    transcriber = WhisperTranscriber(model_size="base")

    with pytest.raises(TranscriptionUnavailableError, match="moov atom not found"):
        transcriber.transcribe(Path("corrupt.mp4"))

    assert devices_used == ["auto"]  # no CPU retry attempted


def test_a_cpu_side_failure_is_not_retried_forever(monkeypatch):
    """Once already on CPU, a second GPU-shaped error string must still just
    raise -- there is no third device to fall back to."""
    devices_used = _install_fake_faster_whisper(
        monkeypatch, [lambda: (_ for _ in ()).throw(_CUBLAS_ERROR)]
    )
    transcriber = WhisperTranscriber(model_size="base")
    transcriber._device = "cpu"

    with pytest.raises(TranscriptionUnavailableError):
        transcriber.transcribe(Path("session.mp4"))

    assert devices_used == ["cpu"]


def test_faster_whisper_not_installed_raises_a_helpful_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    transcriber = WhisperTranscriber()

    with pytest.raises(TranscriptionUnavailableError, match="pip install faster-whisper"):
        transcriber.transcribe(Path("session.mp4"))


@pytest.mark.parametrize(
    "message",
    [
        "Library cublas64_12.dll is not found or cannot be loaded",
        "cuDNN error: CUDNN_STATUS_NOT_INITIALIZED",
        "libcudart.so.12: cannot open shared object file",
        "CUDA driver version is insufficient",
    ],
)
def test_gpu_runtime_failure_detection_covers_the_observed_error_shapes(message):
    assert WhisperTranscriber._looks_like_a_gpu_runtime_failure(RuntimeError(message))


def test_gpu_runtime_failure_detection_does_not_match_unrelated_errors():
    assert not WhisperTranscriber._looks_like_a_gpu_runtime_failure(
        ValueError("Invalid data found when processing input")
    )
