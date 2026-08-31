# src/interfaces/api/routers/recording.py
"""Recording lifecycle and live experiment state.

Moved from src/main.py. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException

from src.backends.discovery import RuntimeCapabilityDiscovery
from src.core.engine import TelemetryEngine
from src.core.exceptions import GDPRConsentError
from src.domain.session_profile import apply_calibration, apply_health_profile
from src.interfaces.api import dependencies as deps
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
    """Background worker for the telemetry loop."""
    try:
        engine.start()
    except Exception as e:
        logger.critical(f"Engine background thread crashed: {e}")


@router.post("/api/recording/start")
def start_recording(config: SessionStartConfig):

    setup_logging()

    if deps.recording_state.is_running:
        raise HTTPException(status_code=400, detail="A telemetry session is already running.")

    if not config.gdpr_consent:
        raise HTTPException(
            status_code=403, detail="Biometric tracking requires explicit GDPR consent."
        )

    patient = deps.patients.get_patient(config.patient_id)
    if not patient or patient["is_anonymized"]:
        raise HTTPException(
            status_code=404, detail="Selected patient not found (or has been erased)."
        )
    if not patient["gdpr_consent_given"]:
        raise HTTPException(
            status_code=403,
            detail="This patient's GDPR consent is not active (never given, or withdrawn). "
            "Recording cannot start until consent is re-established for a new patient record.",
        )

    logger.info(
        f"API Request: Start Pipeline -> Backend: [{config.backend.upper()}], Patient: {patient['patient_id']}"
    )

    if config.backend != "quest_udp":
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
        gdpr_consent=config.gdpr_consent,
        hardware_metadata=hardware_capabilities,
        central_server_url=config.central_server_url,
    )

    engine.subject_metadata["M-IV_Static_Metadata"]["subject_id"] = (
        config.subject_id or patient["display_name"]
    )
    engine.subject_metadata["M-IV_Static_Metadata"]["patient_id"] = patient["patient_id"]
    apply_health_profile(
        engine.subject_metadata, patient, deps.patients.estimate_age_years(patient)
    )
    apply_calibration(engine.subject_metadata, patient, config)
    engine.configured_backend = config.backend
    engine.network_port = config.port

    # Publish before starting the thread: the four live-state routes and the
    # heartbeat's status provider all read this, and a caller can hit them the
    # instant this handler returns.
    deps.recording_state.engine = engine

    try:
        thread = threading.Thread(target=run_engine_thread, args=(engine,), daemon=True)
        deps.recording_state.thread = thread
        thread.start()
        deps.usage_tracker.log_event(
            "recording_start", detail=f"backend={config.backend}, patient={patient['patient_id']}"
        )
        return {
            "status": "recording_started",
            "patient_id": patient["patient_id"],
            "backend": config.backend,
            "session_id": engine.session_id,
        }
    except GDPRConsentError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/recording/stop")
def stop_recording():
    if not deps.recording_state.is_running:
        raise HTTPException(status_code=400, detail="No active recording to stop.")

    # Safely signal the engine to shutdown
    engine = deps.recording_state.engine
    if hasattr(engine, "stop"):
        engine.stop()
        deps.usage_tracker.log_event("recording_stop")
    elif hasattr(engine, "is_running"):
        engine.is_running = False

    return {"status": "recording_stopped"}


def _require_active_engine():
    if not deps.recording_state.is_running:
        raise HTTPException(status_code=400, detail="No active recording session.")
    return deps.recording_state.engine


@router.post("/api/session/scene")
def set_scene(payload: SceneUpdate):
    _require_active_engine().live_state.set_scene(payload.scene_id)
    return {"ok": True}


@router.post("/api/session/mark")
def set_event_marker(payload: EventMarkerUpdate):
    _require_active_engine().live_state.set_event_marker(payload.value)
    return {"ok": True}


@router.post("/api/session/haptic")
def trigger_haptic(payload: HapticTrigger):
    if payload.side not in ("left", "right"):
        raise HTTPException(status_code=400, detail="side must be 'left' or 'right'")
    _require_active_engine().live_state.trigger_haptic(
        payload.side, payload.intensity, payload.duration_sec
    )
    return {"ok": True}


@router.post("/api/session/target")
def set_target_position(payload: TargetPosition):
    _require_active_engine().live_state.set_target_position(payload.x, payload.y, payload.z)
    return {"ok": True}
