# src/av_recording/session_recorder.py
"""Orchestrates one session's A/V capture and transcription. Sits beside
TelemetryEngine, never inside it.

Same relationship ``RecordingDependencies`` has to ``TelemetryEngine``: a
second, independent thing the recording route starts alongside the engine,
gated on its own consent (P-C7, not P-C3) and its own feature flag
(``AVRecordingSettings`` + ``ConsentSettings.enable_av_recording``).

The one invariant that matters more than any other here: **A/V capture is
strictly best-effort. A failure in it must never fail, slow, or stop the
telemetry recording.** Pose and biometric telemetry is the product this
application has shipped and validated for years; A/V recording is three days
old. Every public method here catches what its underlying pieces can raise
(``AVCaptureUnavailableError``, ``TranscriptionUnavailableError``) and turns it
into a logged failure reason on the ``av_recordings`` row, never an exception
that reaches the recording route while telemetry is live.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.av_recording.transcription import TranscriptionUnavailableError, WhisperTranscriber
from src.core.exceptions import AVCaptureUnavailableError
from src.core.interfaces import IAVCaptureBackend
from src.infrastructure.persistence.av_recording_repository import AVRecordingRepository
from src.utils.clock import utc_now_iso
from src.utils.logger import logger


class SessionRecorder:
    """One session's A/V capture, from start to a transcribed (or not) result.

    Args:
        capture: An unstarted capture backend, from
            ``src.av_recording.registry.create_av_capture_backend``.
        repository: Where this session's A/V metadata row lives.
        transcriber: Defaults to a ``WhisperTranscriber`` built from
            ``AVRecordingSettings`` at first use if not given.
    """

    def __init__(
        self,
        capture: IAVCaptureBackend,
        repository: AVRecordingRepository,
        transcriber: WhisperTranscriber | None = None,
    ) -> None:
        self._capture = capture
        self._repository = repository
        self._transcriber = transcriber
        self._session_id: str | None = None
        self._pause_events: list[dict[str, str]] = []
        self._start_failed = False

    def _transcriber_or_default(self) -> WhisperTranscriber:
        if self._transcriber is None:
            from src.config import get_settings

            cfg = get_settings().av_recording
            self._transcriber = WhisperTranscriber(
                model_size=cfg.whisper_model_size, language=cfg.transcription_language
            )
        return self._transcriber

    def start(
        self,
        *,
        session_id: str,
        patient_id: str,
        consent_id: str,
        output_dir: Path,
        capture_backend_name: str,
    ) -> None:
        """Begin capture and record the session's A/V row. Never raises.

        A failure here is logged and leaves this recorder inert (every later
        call is a no-op) -- the caller (the recording route) does not need to
        check a return value to know whether to proceed with telemetry, which
        it always does regardless.
        """
        self._session_id = session_id
        video_path = Path(output_dir) / f"vr_telemetry_{session_id}.mp4"
        try:
            self._capture.start(video_path)
        except AVCaptureUnavailableError as exc:
            logger.warning(f"A/V capture not started for session {session_id}: {exc}")
            self._start_failed = True
            self._repository.create(
                {
                    "session_id": session_id,
                    "patient_id": patient_id,
                    "consent_id": consent_id,
                    "capture_backend": capture_backend_name,
                    "started_at_utc": utc_now_iso(),
                    "created_at_utc": utc_now_iso(),
                }
            )
            self._repository.update(session_id, {"failure_reason": str(exc)})
            return
        self._repository.create(
            {
                "session_id": session_id,
                "patient_id": patient_id,
                "consent_id": consent_id,
                "capture_backend": capture_backend_name,
                "started_at_utc": utc_now_iso(),
                "created_at_utc": utc_now_iso(),
            }
        )

    def pause(self) -> None:
        """The participant's "Pause recording" control. Logged either way."""
        if self._start_failed or self._session_id is None:
            return
        try:
            self._capture.pause()
        except AVCaptureUnavailableError as exc:
            logger.warning(f"A/V pause failed for session {self._session_id}: {exc}")
            return
        self._pause_events.append({"type": "pause", "at_utc": utc_now_iso()})

    def resume(self) -> None:
        if self._start_failed or self._session_id is None:
            return
        try:
            self._capture.resume()
        except AVCaptureUnavailableError as exc:
            logger.warning(f"A/V resume failed for session {self._session_id}: {exc}")
            return
        self._pause_events.append({"type": "resume", "at_utc": utc_now_iso()})

    def stop(self) -> Path | None:
        """Finish capture and persist the result. Never raises.

        Returns:
            The video path, or None if capture never produced one (start
            failed, or capture failed at stop time -- either way the
            ``failure_reason`` column says why, and this is not fatal to the
            telemetry session that was recording alongside it).
        """
        if self._session_id is None:
            return None
        pause_events_json = json.dumps(self._pause_events)
        if self._start_failed:
            self._repository.update(
                self._session_id,
                {"ended_at_utc": utc_now_iso(), "pause_events_json": pause_events_json},
            )
            return None
        try:
            final_path = self._capture.stop()
        except AVCaptureUnavailableError as exc:
            logger.error(f"A/V capture failed for session {self._session_id}: {exc}")
            self._repository.update(
                self._session_id,
                {
                    "failure_reason": str(exc),
                    "ended_at_utc": utc_now_iso(),
                    "pause_events_json": pause_events_json,
                },
            )
            return None
        self._repository.update(
            self._session_id,
            {
                "video_path": str(final_path),
                "ended_at_utc": utc_now_iso(),
                "pause_events_json": pause_events_json,
            },
        )
        return final_path

    def transcribe(self) -> None:
        """Transcribe the stored video. Meant to run on a background thread.

        Never raises: a transcription failure leaves the video in place with
        no transcript and a stated ``failure_reason`` -- it is retriable later
        (re-run against the stored ``video_path``) and never touches the
        session that has already ended by the time this normally runs.
        """
        if self._session_id is None:
            return
        row = self._repository.get(self._session_id)
        if not row or not row.get("video_path"):
            return
        video_path = Path(row["video_path"])
        try:
            transcript = self._transcriber_or_default().transcribe(video_path)
        except TranscriptionUnavailableError as exc:
            logger.error(f"Transcription failed for session {self._session_id}: {exc}")
            self._repository.update(self._session_id, {"failure_reason": str(exc)})
            return

        transcript_path = video_path.with_suffix(".transcript.json")
        transcript.write_json(transcript_path)
        self._repository.update(
            self._session_id,
            {
                "transcript_path": str(transcript_path),
                "transcript_engine": transcript.engine,
                # "Verified" here means the transcription step completed
                # without error -- there is no manual QA step in this
                # pipeline. That is a real limitation of what this column
                # means, stated rather than implied by the name.
                "transcript_verified": 1,
            },
        )
