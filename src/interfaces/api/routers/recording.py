# src/interfaces/api/routers/recording.py
"""Recording lifecycle and live experiment state.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12. Behaviour is unchanged to every caller; the characterisation suite in
tests/characterisation/ is the proof.

The one thing that is different is *internal*: starting and stopping now go
through :class:`~src.interfaces.api.container.RecordingSessionManager` instead
of two module-level globals mutated without synchronisation. Six routes read
that state, one writes it, and they can run concurrently on Starlette's
threadpool. The manager states the contract and holds a lock; the routes below
are the same routes, with the same status codes and the same bodies.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.application.consent import ConsentService, ConsentValidationError
from src.av_recording.registry import create_av_capture_backend, resolve_for_telemetry_backend
from src.av_recording.session_recorder import SessionRecorder
from src.backends.discovery import RuntimeCapabilityDiscovery
from src.backends.registry import resolve as resolve_backend
from src.config import Settings
from src.core.engine import TelemetryEngine
from src.core.exceptions import (
    AVCaptureUnavailableError,
    BackendUnavailableError,
    GDPRConsentError,
)
from src.domain.session_profile import apply_calibration, apply_health_profile
from src.infrastructure.persistence.av_recording_repository import AVRecordingRepository
from src.interfaces.api.container import RecordingSessionManager
from src.interfaces.api.dependencies import (
    AVRecordingsDep,
    CentralUrlDep,
    ConsentsDep,
    PatientsDep,
    RecordingDep,
    SettingsDep,
    UsageTrackerDep,
)
from src.interfaces.api.schemas.recording import (
    EventMarkerUpdate,
    HapticTrigger,
    SceneUpdate,
    SessionStartConfig,
    TargetPosition,
)
from src.utils.logger import logger, setup_logging
from src.utils.metadata import sanitize_metadata

router = APIRouter(tags=["recording"])


def _maybe_start_av_recording(
    *,
    settings: Settings,
    consents: ConsentService,
    av_recordings: AVRecordingRepository,
    recording: RecordingSessionManager,
    engine: TelemetryEngine,
    consent_id: str,
    patient_id: str,
    backend: str,
) -> None:
    """Start A/V capture alongside ``engine``, if the feature and this
    participant's consent (P-C7) both allow it. Never raises.

    Called after :meth:`RecordingSessionManager.start` has published the
    engine, so a capture failure here can never prevent (or be mistaken for)
    a failure to start telemetry -- the two invariant this whole module rests
    on: a telemetry session started is a telemetry session that keeps
    recording, whatever happens to the microphone.
    """
    if not settings.consent.enable_av_recording:
        return
    try:
        if not consents.av_recording_permitted(consent_id):
            return
    except Exception as exc:  # noqa: BLE001 - best-effort: never blocks telemetry
        logger.warning(f"Could not check A/V recording consent for {consent_id}: {exc}")
        return

    capture_backend_name = resolve_for_telemetry_backend(backend)
    if capture_backend_name is None:
        logger.debug(f"No A/V capture backend paired with telemetry backend {backend!r}.")
        return

    try:
        capture = create_av_capture_backend(capture_backend_name)
    except AVCaptureUnavailableError as exc:
        logger.warning(f"A/V capture backend {capture_backend_name!r} unavailable: {exc}")
        return

    session_recorder = SessionRecorder(capture, av_recordings)
    session_recorder.start(
        session_id=engine.session_id,
        patient_id=patient_id,
        consent_id=consent_id,
        output_dir=Path(engine.output_dir),
        capture_backend_name=capture_backend_name,
    )
    recording.attach_av_recorder(session_recorder)


def run_engine_thread(engine: TelemetryEngine):
    """Background worker for the telemetry loop.

    ``TelemetryEngine.start()`` handles the failures it anticipates itself and
    records them on ``engine.failure_reason``; what reaches here is a defect, on
    a thread with nothing above it to catch. Losing that silently is how a
    recording ends up "running" in the UI with no engine behind it.
    """
    try:
        engine.start()
    except Exception as e:  # noqa: BLE001 - thread top level: nothing above it can catch
        engine.is_running = False
        engine.failure_reason = engine.failure_reason or f"engine thread crashed: {e}"
        logger.critical(f"Engine background thread crashed: {e}", exc_info=True)


@router.post("/api/recording/start")
def start_recording(
    config: SessionStartConfig,
    patients: PatientsDep,
    consents: ConsentsDep,
    recording: RecordingDep,
    usage_tracker: UsageTrackerDep,
    central_url: CentralUrlDep,
    settings: SettingsDep,
    av_recordings: AVRecordingsDep,
):

    setup_logging()

    if recording.is_running:
        raise HTTPException(status_code=400, detail="A telemetry session is already running.")

    patient = patients.get_patient(config.patient_id)
    if not patient or patient["is_anonymized"]:
        raise HTTPException(
            status_code=404, detail="Selected patient not found (or has been erased)."
        )
    if not patient["gdpr_consent_given"]:
        raise HTTPException(
            status_code=403,
            detail="This patient's GDPR consent is not active (never given, or withdrawn). "
            "Recording cannot start until the participant gives consent again.",
        )
    # The participant's recorded consent, not a box on this request, is what
    # authorises the recording (GDPR-09). Its id travels with the session so
    # every recording can be traced to the consent it was made under.
    try:
        consent = consents.require_for_recording(patient["patient_id"], config.consent_id)
    except ConsentValidationError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    logger.info(
        f"API Request: Start Pipeline -> Backend: [{config.backend.upper()}], Patient: {patient['patient_id']}"
    )

    if config.backend == "quest_udp" and not settings.acquisition.enable_quest_udp:
        # GDPR-12: refused here, before an engine exists, so the researcher is
        # told why instead of seeing a recording that starts and fails.
        raise HTTPException(
            status_code=400,
            detail="The quest_udp backend is disabled: its receiver accepts unencrypted, "
            "unauthenticated telemetry from the network. Record through OpenXR.",
        )

    if config.backend != "quest_udp":
        # Checked here rather than on the acquisition thread, and before the
        # capability probe below, which boots a throwaway OpenXR instance.
        # `backend` is a free-form string on the wire, and an unrecognised one
        # used to fall through the engine's `else` and start a SteamVR session
        # -- so a typo in the desktop UI recorded a study on whatever hardware
        # happened to be attached. `resolve` imports nothing: this costs a dict
        # lookup.
        try:
            resolve_backend(config.backend)
        except BackendUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        raw_hardware_capabilities: dict[str, Any] = (
            RuntimeCapabilityDiscovery.extract_static_hardware_metadata()
        )
        hardware_capabilities = sanitize_metadata(raw_hardware_capabilities)
    else:
        hardware_capabilities = {
            "openxr_runtime": "Quest_OVRPlugin_Standalone",
            "hmd_model": "Meta Quest Pro",
            "has_eye_tracking": True,
            "transport_protocol": "UDP_Network_Socket",
            "binding_port": config.port,
        }

    engine = TelemetryEngine(
        output_dir=config.output_dir,
        gdpr_consent=True,  # established above, from the consent register
        hardware_metadata=hardware_capabilities,
        # The machine's configured hub, unless this request names one.
        #
        # The engine builds its own uploader from `settings.central.url`, while
        # everything else resolves the address through the local cache -- which
        # is where `POST /api/config/central-server` writes, and therefore where
        # a hub address set in the app actually lives. Those two disagreed, so
        # the *only* way the engine learned about a hub was the desktop UI
        # sending it in this request body, which is why that field shipped with
        # `http://192.168.1.X:9000` hardcoded in it.
        central_server_url=config.central_server_url or central_url,
        backend=config.backend,
        network_port=config.port,
    )

    # The pseudonymous patient id, never the display name (GDPR-11). The
    # fallback used to be `patient["display_name"]`, which stamped the
    # participant's name on the session row and on every upload to the hub.
    engine.subject_metadata["M-IV_Static_Metadata"]["subject_id"] = (
        config.subject_id or patient["patient_id"]
    )
    engine.subject_metadata["M-IV_Static_Metadata"]["patient_id"] = patient["patient_id"]
    engine.subject_metadata["M-IV_Static_Metadata"]["consent_id"] = consent["consent_id"]
    apply_health_profile(engine.subject_metadata, patient, patients.estimate_age_years(patient))
    apply_calibration(engine.subject_metadata, patient, config)

    try:
        # Publishes the engine and starts the thread under one lock, so the four
        # live-state routes and the heartbeat's status provider cannot observe a
        # half-started recording.
        recording.start(engine, run_engine_thread)
        # Best-effort and additive: A/V capture is attempted only after the
        # telemetry engine is published and running. A failure inside this
        # call is caught and logged there, never here -- by the time control
        # reaches this line, the recording this endpoint promised has already
        # started, and nothing below can be allowed to take it back.
        try:
            _maybe_start_av_recording(
                settings=settings,
                consents=consents,
                av_recordings=av_recordings,
                recording=recording,
                engine=engine,
                consent_id=consent["consent_id"],
                patient_id=patient["patient_id"],
                backend=config.backend,
            )
        except Exception as exc:  # noqa: BLE001 - telemetry has already started; must not fail this request
            logger.exception(f"A/V recording setup crashed and was ignored: {exc}")
        usage_tracker.log_event(
            "recording_start", detail=f"backend={config.backend}, patient={patient['patient_id']}"
        )
        return {
            "status": "recording_started",
            "patient_id": patient["patient_id"],
            "backend": config.backend,
            "session_id": engine.session_id,
            "consent_id": consent["consent_id"],
        }
    except GDPRConsentError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except RuntimeError as e:
        # Two requests raced past the is_running check above. Previously the
        # second one won: it overwrote the first engine's reference and left it
        # recording with nothing able to stop it. Now the manager refuses, and
        # the caller gets the same 400 it would have got a microsecond earlier.
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Broad: request boundary: every failure owes the caller a status code
    except Exception as e:
        # The last clause of a request handler, which must answer with *some*
        # status rather than letting the exception become an unlogged 500 from
        # the framework. The two clauses above name the failures this route
        # expects; reaching this one means something unanticipated, so it is
        # logged with its traceback rather than being reduced to a response body.
        logger.exception("Unexpected failure starting a recording")
        raise HTTPException(status_code=500, detail=str(e)) from e


def _finish_av_recording(session_recorder: SessionRecorder) -> None:
    """Stop capture and transcribe, off the request thread. Never raises.

    Runs on its own daemon thread, started by :func:`stop_recording` after the
    HTTP response has already been decided -- transcription can take much
    longer than a request should, and it is not this endpoint's job to make
    the researcher wait for Whisper. Both steps are already best-effort
    internally (see ``SessionRecorder``'s docstring); this wrapper exists only
    so a defect in the orchestration itself (not the capture or transcription
    it calls) cannot crash an unattended daemon thread silently.
    """
    try:
        session_recorder.stop()
        session_recorder.transcribe()
    except Exception:  # noqa: BLE001 - daemon thread top level: nothing above it can catch
        logger.exception("A/V recording stop/transcribe crashed and was ignored")


@router.post("/api/recording/stop")
def stop_recording(recording: RecordingDep, usage_tracker: UsageTrackerDep):
    if not recording.stop():
        raise HTTPException(status_code=400, detail="No active recording to stop.")
    # The old code logged this event only on the branch where the engine had a
    # `stop()` method, and silently skipped it on the `is_running = False`
    # fallback. VRT-12 recorded that as "the fallback never ran"; VRT-14 found
    # the reverse -- the engine had no `stop()` at all, so the *event* was the
    # thing that never ran, and the licence audit trail has been missing every
    # recording_stop it was supposed to contain. The manager collapses the two
    # and the event is now always recorded.
    usage_tracker.log_event("recording_stop")
    session_recorder = recording.pop_av_recorder()
    if session_recorder is not None:
        # Finalising ffmpeg (a graceful stop, up to ~10s) and transcribing
        # (seconds to minutes, depending on length and the configured Whisper
        # model) both happen after this response is sent -- the participant's
        # telemetry session is already over by the time either starts.
        threading.Thread(target=_finish_av_recording, args=(session_recorder,), daemon=True).start()
    return {"status": "recording_stopped"}


def _require_active_engine(recording: RecordingSessionManager) -> TelemetryEngine:
    """The live engine, or the 400 every live-state route returns without one.

    Args:
        recording: The application's recording manager.

    Returns:
        The engine currently recording.

    Raises:
        HTTPException: 400 when nothing is recording.
    """
    engine = recording.engine
    if not recording.is_running or engine is None:
        raise HTTPException(status_code=400, detail="No active recording session.")
    return engine


@router.post("/api/session/scene")
def set_scene(payload: SceneUpdate, recording: RecordingDep):
    _require_active_engine(recording).live_state.set_scene(payload.scene_id)
    return {"ok": True}


@router.post("/api/session/mark")
def set_event_marker(payload: EventMarkerUpdate, recording: RecordingDep):
    _require_active_engine(recording).live_state.set_event_marker(payload.value)
    return {"ok": True}


@router.post("/api/session/haptic")
def trigger_haptic(payload: HapticTrigger, recording: RecordingDep):
    if payload.side not in ("left", "right"):
        raise HTTPException(status_code=400, detail="side must be 'left' or 'right'")
    _require_active_engine(recording).live_state.trigger_haptic(
        payload.side, payload.intensity, payload.duration_sec
    )
    return {"ok": True}


@router.post("/api/session/target")
def set_target_position(payload: TargetPosition, recording: RecordingDep):
    _require_active_engine(recording).live_state.set_target_position(
        payload.x, payload.y, payload.z
    )
    return {"ok": True}


@router.post("/api/av-recording/pause")
def pause_av_recording(recording: RecordingDep):
    """The participant's "pause recording" control (addendum Section 3.3).

    A no-op, not a 400, when no A/V recorder is attached to the current
    session -- pausing a telemetry-only session (A/V recording off, or this
    participant's consent doesn't cover it) is a reasonable click for a
    researcher's UI to allow rather than one it must first ask permission for.
    """
    _require_active_engine(recording)
    session_recorder = recording.av_recorder
    if session_recorder is not None:
        session_recorder.pause()
    return {"ok": True, "av_recording_active": session_recorder is not None}


@router.post("/api/av-recording/resume")
def resume_av_recording(recording: RecordingDep):
    _require_active_engine(recording)
    session_recorder = recording.av_recorder
    if session_recorder is not None:
        session_recorder.resume()
    return {"ok": True, "av_recording_active": session_recorder is not None}
