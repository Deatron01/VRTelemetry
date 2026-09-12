# tests/unit/test_session_recorder.py
"""SessionRecorder's central invariant: A/V capture is strictly best-effort
and must never raise into a caller that is also running telemetry.

Uses fakes for IAVCaptureBackend and the transcriber -- the same seam
test_backend_registry.py's fake backend exercises for IVRBackend -- rather
than real ffmpeg/faster-whisper, which the CI machine need not have installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.av_recording.session_recorder import SessionRecorder
from src.av_recording.transcription import (
    Transcript,
    TranscriptionUnavailableError,
    TranscriptSegment,
)
from src.core.exceptions import AVCaptureUnavailableError
from src.infrastructure.persistence.av_recording_repository import AVRecordingRepository


class _FakeCapture:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls: list[str] = []
        self._output_path: Path | None = None

    def start(self, output_path: Path) -> None:
        self.calls.append("start")
        if "start" in self.fail_on:
            raise AVCaptureUnavailableError("fake start failure")
        self._output_path = Path(output_path)

    def pause(self) -> None:
        self.calls.append("pause")
        if "pause" in self.fail_on:
            raise AVCaptureUnavailableError("fake pause failure")

    def resume(self) -> None:
        self.calls.append("resume")
        if "resume" in self.fail_on:
            raise AVCaptureUnavailableError("fake resume failure")

    def stop(self) -> Path:
        self.calls.append("stop")
        if "stop" in self.fail_on:
            raise AVCaptureUnavailableError("fake stop failure")
        assert self._output_path is not None
        self._output_path.write_bytes(b"fake video")
        return self._output_path


class _FakeTranscriber:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[Path] = []

    def transcribe(self, media_path: Path) -> Transcript:
        self.calls.append(media_path)
        if self.fail:
            raise TranscriptionUnavailableError("fake transcription failure")
        return Transcript(
            engine="fake-whisper",
            language="en",
            segments=(TranscriptSegment(start_sec=0.0, end_sec=1.0, text="hello"),),
        )


@pytest.fixture
def repo(tmp_path: Path) -> AVRecordingRepository:
    return AVRecordingRepository(tmp_path / "metadata.db")


def _start(recorder: SessionRecorder, tmp_path: Path, session_id: str = "sess-1") -> None:
    recorder.start(
        session_id=session_id,
        patient_id="pat-1",
        consent_id="con-1",
        output_dir=tmp_path,
        capture_backend_name="pc_compositor_mirror",
    )


def test_a_normal_recording_produces_a_row_a_video_and_a_transcript(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    capture = _FakeCapture()
    recorder = SessionRecorder(capture, repo, transcriber=_FakeTranscriber())

    _start(recorder, tmp_path)
    video_path = recorder.stop()
    recorder.transcribe()

    assert video_path is not None and video_path.exists()
    row = repo.get("sess-1")
    assert row["video_path"] == str(video_path)
    assert row["transcript_verified"] == 1
    assert row["transcript_path"] is not None
    assert Path(row["transcript_path"]).exists()
    assert json.loads(Path(row["transcript_path"]).read_text())["full_text"] == "hello"


def test_pause_and_resume_are_recorded_as_events(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    capture = _FakeCapture()
    recorder = SessionRecorder(capture, repo)

    _start(recorder, tmp_path)
    recorder.pause()
    recorder.resume()
    recorder.stop()

    row = repo.get("sess-1")
    events = json.loads(row["pause_events_json"])
    assert [e["type"] for e in events] == ["pause", "resume"]


def test_a_capture_start_failure_never_raises_and_still_creates_a_row(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    capture = _FakeCapture(fail_on={"start"})
    recorder = SessionRecorder(capture, repo)

    _start(recorder, tmp_path)  # must not raise

    row = repo.get("sess-1")
    assert row is not None
    assert row["failure_reason"] is not None


def test_after_a_failed_start_pause_resume_and_stop_are_all_no_ops(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    capture = _FakeCapture(fail_on={"start"})
    recorder = SessionRecorder(capture, repo)

    _start(recorder, tmp_path)
    recorder.pause()
    recorder.resume()
    result = recorder.stop()

    assert result is None
    # Capture was never asked to pause/resume/stop -- the whole point of
    # "inert after a failed start" is that nothing downstream is touched.
    assert capture.calls == ["start"]


def test_a_stop_failure_is_recorded_and_returns_none_not_raised(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    capture = _FakeCapture(fail_on={"stop"})
    recorder = SessionRecorder(capture, repo)

    _start(recorder, tmp_path)
    result = recorder.stop()

    assert result is None
    row = repo.get("sess-1")
    assert row["failure_reason"] is not None
    assert row["ended_at_utc"] is not None


def test_pause_failure_is_swallowed_and_not_recorded_as_an_event(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    capture = _FakeCapture(fail_on={"pause"})
    recorder = SessionRecorder(capture, repo)

    _start(recorder, tmp_path)
    recorder.pause()  # must not raise

    recorder.stop()
    row = repo.get("sess-1")
    assert json.loads(row["pause_events_json"]) == []


def test_transcription_failure_leaves_the_video_and_records_why(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    capture = _FakeCapture()
    recorder = SessionRecorder(capture, repo, transcriber=_FakeTranscriber(fail=True))

    _start(recorder, tmp_path)
    video_path = recorder.stop()
    recorder.transcribe()  # must not raise

    assert video_path is not None and video_path.exists()
    row = repo.get("sess-1")
    assert row["transcript_path"] is None
    assert row["transcript_verified"] == 0
    assert row["failure_reason"] is not None


def test_transcribe_before_a_successful_stop_is_a_no_op(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    """No video_path on the row (start failed) -- nothing for the
    transcriber to be handed, and it must not be called at all."""
    capture = _FakeCapture(fail_on={"start"})
    transcriber = _FakeTranscriber()
    recorder = SessionRecorder(capture, repo, transcriber=transcriber)

    _start(recorder, tmp_path)
    recorder.stop()
    recorder.transcribe()

    assert transcriber.calls == []


def test_calling_stop_without_ever_starting_is_a_no_op(repo: AVRecordingRepository) -> None:
    recorder = SessionRecorder(_FakeCapture(), repo)
    assert recorder.stop() is None
