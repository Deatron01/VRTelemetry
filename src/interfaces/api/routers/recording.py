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

from typing import Any

from fastapi import APIRouter, HTTPException

from src.application.consent import ConsentValidationError
from src.backends.discovery import RuntimeCapabilityDiscovery
from src.backends.registry import resolve as resolve_backend
from src.core.engine import TelemetryEngine
from src.core.exceptions import BackendUnavailableError, GDPRConsentError
from src.domain.session_profile import apply_calibration, apply_health_profile
from src.interfaces.api.container import RecordingSessionManager
from src.interfaces.api.dependencies import (
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
