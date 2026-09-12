# tests/unit/test_pc_compositor_capture.py
"""PCCompositorMirrorCapture's ffmpeg process management.

Covers two properties added after a real capture on a microphone-less
Windows machine came back corrupt (empty ffmpeg fallback logic previously
untested at all -- this file existed nowhere before):

1. The audio-missing fallback: when the combined video+audio ffmpeg process
   dies immediately because no dshow microphone exists, capture must retry
   video-only rather than losing the recording outright -- but a genuine
   video-side failure (bad window title, gdigrab itself missing) must still
   raise, not be silently swallowed as if it were an audio problem.
2. Crash safety: ffmpeg's "press q to stop" is read through Win32 console
   input, which a piped stdin (what this class must use, to capture stderr)
   never delivers -- so the graceful stop this class attempts
   (CTRL_BREAK_EVENT, since VRT's own machines proved even that is not
   always honoured -- see _request_graceful_stop's docstring) cannot be
   assumed to work, and a plain, non-fragmented mp4 loses 100% of the
   footage if ffmpeg is ever killed before writing its trailer. The mux
   flags this class adds must actually be present on every ffmpeg
   invocation, and the graceful-stop path must fall through to terminate/
   kill exactly like before when the signal is not honoured.

This module's own constructor resolves a real ffmpeg executable and reads
get_settings() (see _resolve_ffmpeg), which a CI machine need not have
installed -- the same rule test_av_recording_registry.py's docstring states
for the registry. So every test here builds the instance with
object.__new__, setting only the attributes the method under test reads,
and replaces subprocess.Popen with a fake -- no real ffmpeg process is ever
spawned. sys.platform is monkeypatched explicitly rather than relied on,
since this suite runs on both Windows and Linux CI runners (see ci.yml) and
the Windows-only branches must be exercised on both.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from src.av_recording.pc_compositor_capture import (
    PCCompositorMirrorCapture,
    _crash_safe_mux_args_for,
    _graceful_stop_signal,
    _win_creationflags,
)
from src.core.exceptions import AVCaptureUnavailableError

#: subprocess.CREATE_NEW_PROCESS_GROUP and signal.CTRL_BREAK_EVENT exist only
#: on Windows Python builds. Referencing the module attribute directly (as
#: this suite used to) crashed with AttributeError on this suite's Linux CI
#: legs even inside a test that monkeypatches sys.platform to "win32" -- the
#: monkeypatch changes what the code under test sees, not what attributes
#: actually exist on this interpreter's stdlib. Hardcoded to their well-known
#: Windows values so the win32 branch is actually exercised on every runner.
_WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200
_WIN_CTRL_BREAK_EVENT = 1


def _fake_windows(monkeypatch) -> None:
    """Present a *complete* Windows environment to the code under test.

    Patching ``sys.platform`` alone is not one. The functions under test then
    take their win32 branch and dereference
    ``subprocess.CREATE_NEW_PROCESS_GROUP`` / ``signal.CTRL_BREAK_EVENT``,
    which simply do not exist on a Linux interpreter -- so on this suite's
    Linux CI legs the test died with AttributeError inside the function,
    before reaching any assertion. Patching the two attributes in alongside
    the platform is what actually lets the Windows-only branch be exercised
    on both runners, which is what this module's docstring promises.

    ``raising=False`` because on a real Windows runner they are already there
    and this is then a no-op overwrite with the same values.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", _WIN_CREATE_NEW_PROCESS_GROUP, raising=False
    )
    monkeypatch.setattr(signal, "CTRL_BREAK_EVENT", _WIN_CTRL_BREAK_EVENT, raising=False)


def _bare_capture(**overrides: Any) -> PCCompositorMirrorCapture:
    """A PCCompositorMirrorCapture with none of __init__'s ffmpeg/settings
    resolution -- just the attributes the internals under test read."""
    capture = object.__new__(PCCompositorMirrorCapture)
    capture._ffmpeg = overrides.get("ffmpeg", "ffmpeg.exe")
    capture._mirror_window_title = overrides.get("mirror_window_title", "")
    capture._audio_device = overrides.get("audio_device", "")
    capture._video_fps = overrides.get("video_fps", 15)
    capture._output_path = overrides.get("output_path", Path("out.mp4"))
    capture._segments = []
    capture._process = None
    capture._paused = False
    capture._audio_unavailable = overrides.get("audio_unavailable", False)
    return capture


class _FakeStdin:
    def __init__(self) -> None:
        self.written = b""

    def write(self, data: bytes) -> None:
        self.written += data

    def flush(self) -> None:
        pass


class _FakeStderr:
    def __init__(self, text: str) -> None:
        self._data = text.encode("utf-8")

    def read(self) -> bytes:
        return self._data


class _FakeProcess:
    """Stands in for subprocess.Popen -- no real process is ever spawned."""

    def __init__(self, *, alive: bool, stderr_text: str = "") -> None:
        self._returncode: int | None = None if alive else 1
        self.stdin = _FakeStdin()
        self.stderr = _FakeStderr(stderr_text)
        self.signals_sent: list[int] = []
        self.terminated = False
        self.killed = False
        #: Set by a test to make the first wait() after a graceful-stop
        #: attempt time out, exercising the terminate()/kill() fallback.
        self.wait_times_out_once = False

    def poll(self) -> int | None:
        return self._returncode

    def send_signal(self, sig: int) -> None:
        self.signals_sent.append(sig)

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = -15

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.wait_times_out_once:
            self.wait_times_out_once = False
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout or 0)
        # A successful wait() means the process actually exited -- either it
        # was already dead (poll() showed a returncode) or this call is what
        # observes a clean stop (a graceful signal, or terminate()/kill()
        # already having set one).
        if self._returncode is None:
            self._returncode = 0
        return self._returncode


def _patch_popen(monkeypatch: pytest.MonkeyPatch, *processes: _FakeProcess) -> list[list[str]]:
    """Replaces subprocess.Popen with a fake returning `processes` in order.
    Returns the list of cmd argv lists Popen was actually called with."""
    calls: list[list[str]] = []
    queue = list(processes)

    def fake_popen(cmd: list[str], **_kwargs: Any) -> _FakeProcess:
        calls.append(cmd)
        return queue.pop(0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("src.av_recording.pc_compositor_capture.time.sleep", lambda _s: None)
    return calls


# --- platform-conditional helpers -------------------------------------------


def test_creationflags_is_the_process_group_flag_on_windows(monkeypatch):
    _fake_windows(monkeypatch)
    assert _win_creationflags() == _WIN_CREATE_NEW_PROCESS_GROUP


def test_creationflags_is_zero_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert _win_creationflags() == 0


def test_graceful_stop_signal_is_ctrl_break_on_windows(monkeypatch):
    _fake_windows(monkeypatch)
    assert _graceful_stop_signal() == _WIN_CTRL_BREAK_EVENT


def test_graceful_stop_signal_is_none_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert _graceful_stop_signal() is None


# --- crash-safe mux args -----------------------------------------------------


@pytest.mark.parametrize(("fps", "expected_gop"), [(15, 30), (30, 60), (1, 2)])
def test_crash_safe_mux_args_bounds_the_gop_to_two_seconds(fps, expected_gop):
    args = _crash_safe_mux_args_for(fps)
    assert args[:2] == ["-g", str(expected_gop)]
    assert "-movflags" in args
    movflags = args[args.index("-movflags") + 1]
    assert "frag_keyframe" in movflags
    assert "empty_moov" in movflags


# --- audio-missing fallback --------------------------------------------------

_DSHOW_NO_MIC_STDERR = (
    "[dshow @ 0000] Could not enumerate audio only devices (or none found).\n"
    "Error opening input file audio=default.\n"
)


def test_falls_back_to_video_only_when_no_microphone_is_found(monkeypatch):
    capture = _bare_capture()
    video_only = _FakeProcess(alive=True)
    calls = _patch_popen(
        monkeypatch,
        _FakeProcess(alive=False, stderr_text=_DSHOW_NO_MIC_STDERR),
        video_only,
    )

    capture._start_segment()

    assert capture._audio_unavailable is True
    assert capture._process is video_only
    assert len(calls) == 2
    # The retry must not carry the audio input over -- that is the entire
    # point of the fallback existing.
    assert "-f" in calls[1] and "dshow" not in calls[1]
    assert not any("audio=" in arg for arg in calls[1])


def test_a_genuine_video_side_failure_raises_without_a_video_only_retry(monkeypatch):
    capture = _bare_capture()
    calls = _patch_popen(
        monkeypatch,
        _FakeProcess(alive=False, stderr_text="Could not find window 'nonexistent title'\n"),
    )

    with pytest.raises(AVCaptureUnavailableError):
        capture._start_segment()

    # Must not have masked a real video-side failure as an audio one and
    # retried -- that would swallow the actual error and silently produce a
    # segment with no video either, or double the startup wait for nothing.
    assert len(calls) == 1


def test_once_audio_is_known_unavailable_later_segments_skip_straight_to_video_only(
    monkeypatch,
):
    capture = _bare_capture(audio_unavailable=True)
    video_only = _FakeProcess(alive=True)
    calls = _patch_popen(monkeypatch, video_only)

    capture._start_segment()

    assert len(calls) == 1  # no repeated audio probe on every segment
    assert not any("audio=" in arg for arg in calls[0])
    assert capture._process is video_only


@pytest.mark.parametrize("audio_unavailable", [False, True])
def test_every_ffmpeg_invocation_carries_the_crash_safe_mux_flags(monkeypatch, audio_unavailable):
    capture = _bare_capture(audio_unavailable=audio_unavailable, video_fps=15)
    calls = _patch_popen(monkeypatch, _FakeProcess(alive=True))

    capture._start_segment()

    (cmd,) = calls
    assert "-movflags" in cmd
    assert "-g" in cmd and cmd[cmd.index("-g") + 1] == "30"


# --- graceful stop / crash-safety fallback -----------------------------------


def test_finish_segment_sends_ctrl_break_on_windows_and_stops_cleanly(monkeypatch):
    _fake_windows(monkeypatch)
    capture = _bare_capture()
    process = _FakeProcess(alive=True)
    capture._process = process  # type: ignore[assignment]

    capture._finish_segment()

    assert process.signals_sent == [_WIN_CTRL_BREAK_EVENT]
    assert not process.terminated
    assert not process.killed


def test_finish_segment_falls_back_to_terminate_then_kill_when_the_signal_is_not_honoured(
    monkeypatch,
):
    """Mirrors what was actually observed on a real machine: CTRL_BREAK_EVENT
    sent, ffmpeg never exits, so the pre-existing terminate()/kill() ladder
    must still run -- crash-safety (the mux flags) is what makes this an
    acceptable outcome now, not a data-loss bug."""
    _fake_windows(monkeypatch)
    capture = _bare_capture()
    process = _FakeProcess(alive=True)
    process.wait_times_out_once = True
    capture._process = process  # type: ignore[assignment]

    capture._finish_segment()

    assert process.signals_sent == [_WIN_CTRL_BREAK_EVENT]
    assert process.terminated
    assert not process.killed  # terminate()'s own wait() succeeded


def test_finish_segment_writes_q_to_stdin_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    capture = _bare_capture()
    process = _FakeProcess(alive=True)
    capture._process = process  # type: ignore[assignment]

    capture._finish_segment()

    assert process.signals_sent == []
    assert process.stdin.written == b"q"


def test_finish_segment_is_a_no_op_when_the_process_already_exited(monkeypatch):
    _fake_windows(monkeypatch)
    capture = _bare_capture()
    process = _FakeProcess(alive=False)
    capture._process = process  # type: ignore[assignment]

    capture._finish_segment()  # must not raise or touch signals/terminate

    assert process.signals_sent == []
    assert not process.terminated


def test_launch_starts_ffmpeg_in_its_own_process_group_on_windows(monkeypatch):
    _fake_windows(monkeypatch)
    capture = _bare_capture()
    seen_kwargs: dict[str, Any] = {}

    def fake_popen(cmd: list[str], **kwargs: Any) -> _FakeProcess:
        seen_kwargs.update(kwargs)
        return _FakeProcess(alive=True)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("src.av_recording.pc_compositor_capture.time.sleep", lambda _s: None)

    capture._launch(["ffmpeg.exe", "-y"])

    assert seen_kwargs["creationflags"] == _WIN_CREATE_NEW_PROCESS_GROUP
