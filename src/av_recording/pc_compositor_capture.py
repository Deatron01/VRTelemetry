# src/av_recording/pc_compositor_capture.py
"""Capture the VR runtime's compositor mirror window + microphone, via ffmpeg.

Not a vendor SDK integration (``ovr_GetMirrorTexture`` / an OpenXR compositor
extension) -- that would mean three more optional native dependencies on top
of pyopenxr/openvr/pyovr, each with its own availability story, to grab a
video stream that exists for exactly this purpose already: every one of the
three PCVR runtimes (SteamVR, the Oculus/Meta runtime, and OpenXR runtimes
generally) shows a 2D "mirror" of the headset view in a desktop window while a
session is active. ``ffmpeg -f gdigrab`` capturing that window by title, plus
``-f dshow`` for the microphone, is a few hundred lines of subprocess
management instead of three SDKs -- and is exactly the tool this project
already reaches for elsewhere (``tools/generate_hub_certificate.py`` for TLS,
rather than hand-rolled ASN.1).

Windows-only by construction (``gdigrab`` and ``dshow`` are ffmpeg's Windows
capture devices). That matches this project generally: SteamVR and the Oculus
runtime are also Windows-only in practice here.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from src.core.exceptions import AVCaptureUnavailableError
from src.core.interfaces import IAVCaptureBackend
from src.utils.logger import logger

#: How long to wait, after launching ffmpeg, before checking it did not die
#: immediately (a bad device name, a title that matches no window, ffmpeg
#: itself missing a codec). Long enough for ffmpeg to fail fast; short enough
#: not to make every recording start feel sluggish.
_STARTUP_CHECK_SEC = 1.5

#: How long to wait for ffmpeg to finalise a segment after asking it to stop
#: gracefully (see ``_request_graceful_stop``) before killing it. Short,
#: deliberately: a graceful stop that works at all is near-instant (write a
#: small trailer/mfra box), and ``_crash_safe_mux_args`` means an ungraceful
#: kill no longer loses the whole segment -- so this is worth very little
#: extra wait once it is clear the signal was not honoured (a participant or
#: researcher clicking "stop" should not hang for it).
_GRACEFUL_STOP_TIMEOUT_SEC = 3.0


def _win_creationflags() -> int:
    """``CREATE_NEW_PROCESS_GROUP`` on Windows, so a later CTRL_BREAK_EVENT
    (see ``_request_graceful_stop``) targets ffmpeg alone and not this
    process too. A plain ``if`` on ``sys.platform`` (rather than a ternary or
    a module-level constant) so mypy's platform-conditional reachability
    analysis skips the Windows-only attribute on non-Windows checks -- this
    module runs only on Windows, but is still imported and unit-tested
    (with ``subprocess.Popen`` mocked) on other platforms.
    """
    if sys.platform == "win32":
        return subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def _graceful_stop_signal() -> int | None:
    """``CTRL_BREAK_EVENT`` on Windows, ``None`` elsewhere -- see
    ``_win_creationflags`` for why this is a platform ``if`` rather than a
    constant.
    """
    if sys.platform == "win32":
        return signal.CTRL_BREAK_EVENT
    return None


def _crash_safe_mux_args_for(video_fps: int) -> list[str]:
    """Encoder/muxer flags that keep most of the recording even if ffmpeg is
    ever killed without a chance to finalise the file (see
    ``PCCompositorMirrorCapture._request_graceful_stop``: the polite path is
    attempted first, but this is the backstop for whenever it doesn't take).

    A plain mp4 only writes its ``moov`` atom (the sample index -- without
    it, no player or ``ffprobe`` can read *any* frame) once at the very end,
    in ``av_write_trailer()``. Kill the process before that -- a hung
    graceful-stop signal, a crash, the app itself being force-closed -- and
    every frame captured so far is unrecoverable even though it is sitting
    right there in the file, which is exactly the failure this whole
    capture exists to avoid.

    ``-movflags frag_keyframe+empty_moov`` (the standard "fragmented mp4" /
    fMP4 layout used by DASH and HLS-fmp4) writes an empty ``moov``
    immediately and flushes a self-contained fragment to disk at every
    keyframe, so the file is playable up to the last completed fragment no
    matter when the process dies; only the one fragment still being written
    at the moment of the kill can be lost. ``default_base_moof`` keeps each
    fragment's offsets self-relative, which is what makes a fragment usable
    on its own instead of only in combination with the initial header.
    ``-g`` (a keyframe at least every 2 seconds, at the configured frame
    rate) bounds how much that worst case can lose -- x264's default GOP is
    ~16s, which would otherwise mean up to 16s of unrecoverable video on an
    ungraceful stop.

    A module-level function (rather than a method) so it is a plain,
    dependency-free unit to test against every ``video_fps`` value without
    constructing a whole capture instance.
    """
    return [
        "-g",
        str(max(1, video_fps * 2)),
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
    ]


def _resolve_ffmpeg(configured_path: str) -> str:
    """The ffmpeg executable to run, or raise naming what to install.

    Tries, in order: an explicitly configured path
    (``settings.av_recording.ffmpeg_path``), ``ffmpeg`` on ``PATH``, and the
    binary the optional ``imageio-ffmpeg`` package bundles -- the same
    dependency ``moviepy`` and a good few other Python video tools rely on,
    so it is a reasonable thing to ask a researcher to ``pip install`` without
    asking them to separately manage a system ffmpeg install.
    """
    if configured_path:
        if not Path(configured_path).is_file():
            raise AVCaptureUnavailableError(
                f"av_recording.ffmpeg_path is set to {configured_path!r}, which does not exist."
            )
        return configured_path

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - resolving a tool path, not recording
        logger.debug(f"imageio_ffmpeg present but could not resolve an ffmpeg binary: {exc}")

    raise AVCaptureUnavailableError(
        "No ffmpeg executable found. Install ffmpeg and put it on PATH, set "
        "av_recording.ffmpeg_path in config.toml, or `pip install imageio-ffmpeg`."
    )


class PCCompositorMirrorCapture(IAVCaptureBackend):
    """gdigrab of the runtime's mirror window + dshow microphone, via ffmpeg.

    Pause/resume is implemented as segments, not a true pause of one ffmpeg
    process: Windows ffmpeg has no clean "suspend capture, keep the file open"
    mode, and stopping/restarting the process is the same operation
    :meth:`stop` already needs at session end. Each ``start``/``resume`` opens
    a new segment file; :meth:`stop` concatenates them (stream-copy, no
    re-encode, since every segment shares the same encoder settings) into the
    final output and removes the parts. A session with no pauses has exactly
    one segment, which is renamed into place rather than re-muxed.
    """

    def __init__(self) -> None:
        from src.config import get_settings

        cfg = get_settings().av_recording
        self._ffmpeg = _resolve_ffmpeg(cfg.ffmpeg_path)
        self._mirror_window_title = cfg.mirror_window_title
        self._audio_device = cfg.audio_device
        self._video_fps = cfg.video_fps

        self._output_path: Path | None = None
        self._segments: list[Path] = []
        self._process: subprocess.Popen[bytes] | None = None
        self._paused = False
        #: Set once a segment has had to fall back to video-only (no working
        #: dshow audio device found), so every later segment in this same
        #: recording skips straight to video-only instead of re-discovering
        #: the same failure on every pause/resume. The video is the thing a
        #: researcher can least afford to lose; audio is the part that is
        #: allowed to be missing.
        self._audio_unavailable = False

    # --- IAVCaptureBackend ---------------------------------------------------

    def start(self, output_path: Path) -> None:
        if self._output_path is not None:
            raise AVCaptureUnavailableError("start() called twice on the same capture backend.")
        self._output_path = Path(output_path)
        self._paused = False
        self._start_segment()

    def pause(self) -> None:
        if self._output_path is None:
            raise AVCaptureUnavailableError("pause() called before start().")
        if self._paused:
            return
        self._finish_segment()
        self._paused = True

    def resume(self) -> None:
        if self._output_path is None:
            raise AVCaptureUnavailableError("resume() called before start().")
        if not self._paused:
            return
        self._paused = False
        self._start_segment()

    def stop(self) -> Path:
        if self._output_path is None:
            raise AVCaptureUnavailableError("stop() called before start().")
        if not self._paused:
            self._finish_segment()

        output_path = self._output_path
        segments = [s for s in self._segments if s.exists() and s.stat().st_size > 0]
        if not segments:
            raise AVCaptureUnavailableError(
                "No usable A/V segment was captured -- ffmpeg produced no non-empty output. "
                "Check that a compositor mirror window is visible and a microphone is bound."
            )

        if len(segments) == 1:
            shutil.move(str(segments[0]), str(output_path))
        else:
            self._concat_segments(segments, output_path)
            for segment in segments:
                segment.unlink(missing_ok=True)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise AVCaptureUnavailableError(
                f"Capture finished but {output_path} is missing or empty."
            )
        return output_path

    # --- internals ------------------------------------------------------------

    def _video_source_args(self) -> list[str]:
        if self._mirror_window_title:
            return [
                "-f",
                "gdigrab",
                "-framerate",
                str(self._video_fps),
                "-i",
                f"title={self._mirror_window_title}",
            ]
        logger.warning(
            "av_recording.mirror_window_title is not set -- capturing the whole desktop "
            "instead of just the VR runtime's mirror window. Set it to the runtime's mirror "
            "window title to avoid recording whatever else is on screen."
        )
        return ["-f", "gdigrab", "-framerate", str(self._video_fps), "-i", "desktop"]

    def _audio_source_args(self) -> list[str]:
        device = self._audio_device or "default"
        return ["-f", "dshow", "-i", f"audio={device}"]

    def _crash_safe_mux_args(self) -> list[str]:
        return _crash_safe_mux_args_for(self._video_fps)

    #: Substrings ffmpeg's dshow input prints when no usable audio device
    #: exists (no microphone attached, or the configured/"default" name
    #: matches nothing) -- as opposed to a video-side failure (bad window
    #: title, gdigrab itself missing), which this must not mask.
    _AUDIO_FAILURE_MARKERS = (
        "could not enumerate audio",
        "could not find audio",
        "audio device",
        "[dshow",
    )

    def _launch(self, cmd: list[str]) -> tuple[subprocess.Popen[bytes] | None, str]:
        """Start ``cmd`` and wait out the startup check.

        Returns:
            ``(process, "")`` if it is still running after the check, or
            ``(None, stderr_tail)`` if it exited immediately.
        """
        process = subprocess.Popen(  # noqa: S603 - fixed executable path resolved above, no shell
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_win_creationflags(),
        )
        time.sleep(_STARTUP_CHECK_SEC)
        if process.poll() is None:
            return process, ""
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return None, stderr

    def _start_segment(self) -> None:
        assert self._output_path is not None
        index = len(self._segments)
        segment_path = self._output_path.with_suffix(f".part{index}.mp4")
        video_args = self._video_source_args()

        if not self._audio_unavailable:
            cmd = [
                self._ffmpeg,
                "-y",
                *video_args,
                *self._audio_source_args(),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                *self._crash_safe_mux_args(),
                "-c:a",
                "aac",
                str(segment_path),
            ]
            logger.info(f"Starting A/V capture segment {index}: {segment_path.name}")
            process, stderr = self._launch(cmd)
            if process is not None:
                self._process = process
                self._segments.append(segment_path)
                return

            if not any(marker in stderr.lower() for marker in self._AUDIO_FAILURE_MARKERS):
                raise AVCaptureUnavailableError(
                    f"ffmpeg exited immediately (starting A/V capture). Check "
                    f"av_recording.mirror_window_title and av_recording.audio_device. "
                    f"ffmpeg said: {stderr[-800:]}"
                )
            # The video source is fine; only the audio device is the problem.
            # Falling back keeps the recording -- silent -- rather than losing
            # it outright, since the video is the harder-to-reconstruct half.
            logger.warning(
                "No usable microphone found for A/V capture (av_recording.audio_device="
                f"{self._audio_device!r}); continuing video-only for this session. ffmpeg "
                f"said: {stderr[-400:]}"
            )
            self._audio_unavailable = True

        cmd = [
            self._ffmpeg,
            "-y",
            *video_args,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            *self._crash_safe_mux_args(),
            str(segment_path),
        ]
        logger.info(f"Starting video-only capture segment {index}: {segment_path.name}")
        process, stderr = self._launch(cmd)
        if process is None:
            raise AVCaptureUnavailableError(
                f"ffmpeg exited immediately (starting video-only capture, after the "
                f"microphone was already found unavailable). Check "
                f"av_recording.mirror_window_title. ffmpeg said: {stderr[-800:]}"
            )
        self._process = process
        self._segments.append(segment_path)

    def _request_graceful_stop(self, process: subprocess.Popen[bytes]) -> None:
        """Ask ffmpeg to finish this segment and write its trailer.

        ffmpeg's documented "press q to stop" is read through Win32's
        console-input API, which only ever sees keystrokes typed into a real
        console -- a piped ``stdin`` (what :meth:`_launch` gives it, so this
        class can capture its stderr) is never read that way on Windows.
        Writing ``b"q"`` to that pipe is therefore a silent no-op here: every
        segment used to time out and fall through to ``terminate()``/
        ``kill()``, which stops ffmpeg before it writes the moov atom and
        leaves a truncated, unplayable ``.mp4`` -- exactly the file this
        capture exists to produce. On Windows, ffmpeg instead installs a
        console-control handler that treats ``CTRL_BREAK_EVENT`` the same as
        SIGINT elsewhere (finish encoding, write the trailer, exit), and
        :meth:`_launch` starts it in its own process group
        (``CREATE_NEW_PROCESS_GROUP``) so that event can be aimed at ffmpeg
        alone without also interrupting this process.
        """
        stop_signal = _graceful_stop_signal()
        if stop_signal is not None:
            process.send_signal(stop_signal)
            return
        if process.stdin:
            process.stdin.write(b"q")
            process.stdin.flush()

    def _finish_segment(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            self._request_graceful_stop(process)
            process.wait(timeout=_GRACEFUL_STOP_TIMEOUT_SEC)
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("ffmpeg did not stop gracefully within the timeout; terminating it.")
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()

    def _concat_segments(self, segments: list[Path], output_path: Path) -> None:
        list_file = output_path.with_suffix(".concat.txt")
        list_file.write_text(
            "\n".join(f"file '{segment.resolve().as_posix()}'" for segment in segments),
            encoding="utf-8",
        )
        cmd = [
            self._ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=120)  # noqa: S603
            if result.returncode != 0:
                raise AVCaptureUnavailableError(
                    f"ffmpeg could not join {len(segments)} paused-recording segments: "
                    f"{result.stderr.decode('utf-8', errors='replace')[-800:]}"
                )
        finally:
            list_file.unlink(missing_ok=True)
