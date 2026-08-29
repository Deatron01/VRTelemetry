# src/main.py

import sys
import logging
import argparse
import threading
import sqlite3
import io
import pandas as pd
import requests as http_requests
from typing import Dict, Any, Optional, List
from src.license_service.manager import LicenseManager
import platform
import uuid as uuid_lib

# --- New API Imports ---
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.utils.logger import setup_logging, logger
from src.core.engine import TelemetryEngine
from src.backends.discovery import RuntimeCapabilityDiscovery
from src.core.exceptions import GDPRConsentError
from src.eye_tracking.factory import EyeTrackingFactory
from src.storage.usage_tracker import UsageTracker
_usage = UsageTracker()

def parse_arguments() -> argparse.Namespace:
    """
    Constructs the operational CLI argument parser for framework initialization.
    """
    parser = argparse.ArgumentParser(description="VRTelemetry: Headless Biometric Acquisition Framework")
    parser.add_argument(
        "--gdpr-consent", 
        action="store_true", 
        help="Explicitly confirm subject consent for biometric data collection. Must be provided to run."
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="Sessions", 
        help="Target directory for Parquet data matrices and SQLite metadata."
    )
    parser.add_argument(
        "--subject-id", 
        type=str, 
        default="SUB_UNKN_01", 
        help="Anonymized UUID for the active test subject."
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["auto", "openxr", "oculus", "steamvr", "quest_udp"],
        default="auto",
        help="Enforce a specific runtime hardware backend wrapper or standalone network telemetry worker."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5005,
        help="Incoming network port target when operating under 'quest_udp' stream backend mode."
    )
    return parser.parse_args()

def sanitize_metadata(data: Any) -> Any:
    """
    Recursively decodes C-style byte strings into UTF-8 strings 
    to prevent JSON serialization crashes in the database manager.
    """
    if isinstance(data, dict):
        return {k: sanitize_metadata(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_metadata(v) for v in data]
    elif isinstance(data, bytes):
        return data.decode('utf-8', errors='ignore')
    return data

def execute_pipeline() -> None:
    """
    Main orchestration bootstrapper. Extracts runtime topology, constructs capability 
    maps, and spins up the isolated tracking background layers.
    """
    setup_logging()
    args = parse_arguments()
    
    logger.info("=== VRTelemetry Pro Background Session ===")
    
    if not args.gdpr_consent:
        logger.error("Launch aborted: Biometric tracking requires explicit --gdpr-consent flag.")
        sys.exit(1)
        
    logger.info(f"Selected execution pipeline mode: Enforced Backend -> [{args.backend.upper()}]")
    print(f"DEBUG: Factory Registry contains: {EyeTrackingFactory._registry}")
    # Extract native runtime metadata if standard PCVR hardware mode is active
    if args.backend != "quest_udp":
        logger.info("Evaluating OpenXR hardware topology and extension capabilities...")
        raw_hardware_capabilities: Dict[str, Any] = RuntimeCapabilityDiscovery.extract_static_hardware_metadata()
        hardware_capabilities = sanitize_metadata(raw_hardware_capabilities)
    else:
        # Generate virtual network context payload mapping for Quest standalone stream
        hardware_capabilities = { 
            "openxr_runtime": "Quest_OVRPlugin_Standalone",
            "hmd_model": "Meta Quest Pro",
            "has_eye_tracking": True,
            "transport_protocol": "UDP_Network_Socket",
            "binding_port": args.port
        }
    
    logger.info(f"Detected Runtime: {hardware_capabilities.get('openxr_runtime')}")
    logger.info(f"Detected HMD: {hardware_capabilities.get('hmd_model')}")
    logger.info(f"Eye Tracking Capability: {'Available' if hardware_capabilities.get('has_eye_tracking') else 'Unavailable'}")
    
    # Engine requires robust static context for AI downstream tracking
    engine = TelemetryEngine(
        output_dir=args.output,
        gdpr_consent=args.gdpr_consent,
        hardware_metadata=hardware_capabilities
    )
    
    # Inject runtime execution configurations into context maps before startup sequence
    engine.subject_metadata["M-IV_Static_Metadata"]["subject_id"] = args.subject_id
    
    # Inform backend engine context regarding specific protocol drivers
    engine.configured_backend = args.backend
    engine.network_port = args.port
        
    try:
        engine.start()
    except GDPRConsentError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unhandled framework panic: {e}", exc_info=True)
        sys.exit(1)


# =====================================================================
# --- APPENDED FASTAPI WEB SERVICE CONFIGURATION ---
# =====================================================================

app = FastAPI(title="VRTelemetry Unified Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "Sessions/vr_metadata.db"

# Global state for background engine threading
active_engine: Optional[TelemetryEngine] = None
engine_thread: Optional[threading.Thread] = None

class SessionStartConfig(BaseModel):
    patient_id: str
    subject_id: str = "SUB_UNKN_01"
    backend: str = "auto"
    port: int = 5005
    gdpr_consent: bool
    output_dir: str = "Sessions"
    central_server_url: str = "http://192.168.1.X:9000"

class SessionUpdate(BaseModel):
    subject_id: Optional[str] = None
    start_timestamp_utc: Optional[str] = None
    subject_vr_exp: Optional[str] = None
    session_rating: Optional[int] = None

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def run_engine_thread(engine: TelemetryEngine):
    """Background worker for the telemetry loop."""
    try:
        engine.start()
    except Exception as e:
        logger.critical(f"Engine background thread crashed: {e}")

# --- API Endpoints ---

@app.post("/api/upload-telemetry")
async def upload_telemetry(file: UploadFile = File(...)):
    """
    Fogadja a nagyméretű Parquet fájlt, és memóriahatékonyan feldolgozza Pandas segítségével.
    """
    content = await file.read()
    
    # A Pandas nagyságrendekkel memóriahatékonyabb a Parquet olvasásában
    df = pd.read_parquet(io.BytesIO(content))
    original_count = len(df)
    
    # Ritkítás (Downsampling) max 60,000 sorra a React stabil működéséhez
    step = max(1, original_count // 60000)
    df_sampled = df.iloc[::step].copy()
    
    # 1. JAVÍTÁS: Nanosecond Timestamp túlcsordulás megelőzése JS-ben
    # Levonjuk az első frame idejét mindenből, így hatalmas, memóriagyilkos számok 
    # helyett 0-ról induló másodperceket kap a React.
    if 'timestamp_ns' in df_sampled.columns:
        first_ts = df['timestamp_ns'].iloc[0]
        df_sampled['timestamp_ns'] = df_sampled['timestamp_ns'] - first_ts
        
    # 2. JAVÍTÁS: Kvaterniók (3D forgatás) megmentése
    # A korábbi fillna(0) a hiányzó w értékeket 0-ra állította, ami Three.js NaN összeomlást okozott.
    # Ez a sor a hiányzó adatokat szigorúan `null`-ként küldi át a JSON-ben, így a 
    # React biztonsági fallbackje (pl. `f.left_eye_rot_w ?? 1`) végre tud aktiválódni!
    df_sampled = df_sampled.where(pd.notnull(df_sampled), None)
    
    return {
        "original_frames": original_count,
        "columns": df.columns.tolist(),
        "frames": df_sampled.to_dict(orient="records")
    }

@app.get("/api/sessions")
def get_all_sessions():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    session_id, patient_id, start_timestamp_utc, subject_id, 
                    hmd_model, tracking_space_type, total_dropped_frames,
                    session_rating
                FROM session_metadata
                ORDER BY created_at DESC
            """)
            sessions = cursor.fetchall()
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Enrich with patient display names. Sessions recorded before patient
    # linking existed (or where the patient was since erased) fall back
    # gracefully rather than breaking the listing.
    patient_cache: Dict[str, Optional[str]] = {}
    for s in sessions:
        pid = s.get("patient_id")
        if not pid:
            s["patient_display_name"] = None
            continue
        if pid not in patient_cache:
            p = _patients.get_patient(pid)
            patient_cache[pid] = p["display_name"] if p and not p["is_anonymized"] else "[Erased Patient]" if p else None
        s["patient_display_name"] = patient_cache[pid]

    return sessions

@app.get("/api/sessions/{session_id}")
def get_session_details(session_id: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM session_metadata WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")
            return row
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/sessions/{session_id}")
def update_session(session_id: str, update_data: SessionUpdate):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            update_fields = {k: v for k, v in update_data.dict().items() if v is not None}
            if not update_fields:
                return {"status": "no changes"}

            set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
            values = list(update_fields.values())
            values.append(session_id)

            cursor.execute(f"UPDATE session_metadata SET {set_clause} WHERE session_id = ?", values)
            conn.commit()
            
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Session not found")
                
            return {"status": "success", "updated_fields": list(update_fields.keys())}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/recording/start")
def start_recording(config: SessionStartConfig):
    global active_engine, engine_thread

    setup_logging()

    if active_engine and getattr(active_engine, 'is_running', False):
        raise HTTPException(status_code=400, detail="A telemetry session is already running.")

    if not config.gdpr_consent:
        raise HTTPException(status_code=403, detail="Biometric tracking requires explicit GDPR consent.")

    patient = _patients.get_patient(config.patient_id)
    if not patient or patient["is_anonymized"]:
        raise HTTPException(status_code=404, detail="Selected patient not found (or has been erased).")
    if not patient["gdpr_consent_given"]:
        raise HTTPException(
            status_code=403,
            detail="This patient's GDPR consent is not active (never given, or withdrawn). "
                   "Recording cannot start until consent is re-established for a new patient record.",
        )

    logger.info(f"API Request: Start Pipeline -> Backend: [{config.backend.upper()}], Patient: {patient['patient_id']}")

    if config.backend != "quest_udp":
        raw_hardware_capabilities: Dict[str, Any] = RuntimeCapabilityDiscovery.extract_static_hardware_metadata()
        hardware_capabilities = sanitize_metadata(raw_hardware_capabilities)
    else:
        hardware_capabilities = {
            "openxr_runtime": "Quest_OVRPlugin_Standalone",
            "hmd_model": "Meta Quest Pro",
            "has_eye_tracking": True,
            "transport_protocol": "UDP_Network_Socket",
            "binding_port": config.port
        }

    active_engine = TelemetryEngine(
        output_dir=config.output_dir,
        gdpr_consent=config.gdpr_consent,
        hardware_metadata=hardware_capabilities,
        central_server_url=config.central_server_url,
    )

    active_engine.subject_metadata["M-IV_Static_Metadata"]["subject_id"] = config.subject_id or patient["display_name"]
    active_engine.subject_metadata["M-IV_Static_Metadata"]["patient_id"] = patient["patient_id"]
    active_engine.configured_backend = config.backend
    active_engine.network_port = config.port

    try:
        engine_thread = threading.Thread(target=run_engine_thread, args=(active_engine,), daemon=True)
        engine_thread.start()
        _usage.log_event("recording_start", detail=f"backend={config.backend}, patient={patient['patient_id']}")
        return {"status": "recording_started", "patient_id": patient["patient_id"], "backend": config.backend}
    except GDPRConsentError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/recording/stop")
def stop_recording():
    global active_engine
    if not active_engine or not getattr(active_engine, 'is_running', False):
        raise HTTPException(status_code=400, detail="No active recording to stop.")
    
    # Safely signal the engine to shutdown
    if hasattr(active_engine, 'stop'):
        active_engine.stop() 
        _usage.log_event("recording_stop")
    elif hasattr(active_engine, 'is_running'):
        active_engine.is_running = False

    return {"status": "recording_stopped"}

from src.license_service.local_cache import LocalLicenseCache
from src.storage.session_uploader import SessionUploader

_local_cache = LocalLicenseCache()
DEFAULT_CENTRAL_URL = "http://127.0.0.1:9000"

def _central_url() -> str:
    return _local_cache.get_config("central_server_url", DEFAULT_CENTRAL_URL)


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    org_name: str
    display_name: str = ""

class AuthLoginRequest(BaseModel):
    email: str
    password: str

class CentralUrlConfig(BaseModel):
    central_server_url: str


@app.post("/api/auth/register")
def api_register(payload: AuthRegisterRequest):
    try:
        r = http_requests.post(f"{_central_url()}/auth/register", data=payload.dict(), timeout=10)
    except http_requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", "registration_failed"))
    return r.json()


@app.post("/api/auth/login")
def api_login(payload: AuthLoginRequest):
    try:
        r = http_requests.post(f"{_central_url()}/auth/login", data=payload.dict(), timeout=10)
    except http_requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", "login_failed"))

    data = r.json()
    _local_cache.save_session(data["session_token"], data["user_id"], data["email"], data.get("display_name", ""))
    return data


@app.post("/api/auth/logout")
def api_logout():
    session = _local_cache.get_session()
    if session and session.get("session_token"):
        try:
            http_requests.post(f"{_central_url()}/auth/logout",
                                data={"session_token": session["session_token"]}, timeout=5)
        except http_requests.RequestException:
            pass  # best-effort — clear local state regardless
    _local_cache.clear_session()
    return {"ok": True}


@app.get("/api/auth/session")
def api_session():
    """
    Called on app boot to decide whether to show the login screen or the app shell.
    Validates against the central server when reachable; falls back to trusting
    the local cache if the server is unreachable, so a LAN blip mid-recording
    doesn't boot the researcher out mid-session.
    """
    session = _local_cache.get_session()
    if not session or not session.get("session_token"):
        return {"authenticated": False}

    try:
        r = http_requests.get(f"{_central_url()}/auth/session",
                               params={"session_token": session["session_token"]}, timeout=5)
        if r.status_code == 200:
            return {"authenticated": True, **r.json()}
        else:
            _local_cache.clear_session()
            return {"authenticated": False}
    except http_requests.RequestException:
        # Central server unreachable — trust the local cache rather than lock the researcher out
        return {"authenticated": True, "email": session["email"], "display_name": session["display_name"],
                "offline": True}


@app.get("/api/config/central-server")
def get_central_config():
    return {"central_server_url": _central_url()}


@app.post("/api/config/central-server")
def set_central_config(payload: CentralUrlConfig):
    _local_cache.set_config("central_server_url", payload.central_server_url)
    return {"ok": True, "central_server_url": payload.central_server_url}

@app.get("/api/sync/status")
def sync_status():
    pending_sessions = _local_cache.list_pending_uploads()
    pending_patients = _local_cache.list_pending_patient_syncs()
    return {
        "pending_count": len(pending_sessions) + len(pending_patients),
        "pending_sessions": len(pending_sessions),
        "pending_patients": len(pending_patients),
        "pending": [
            {"session_id": p["session_id"], "attempts": p["attempts"], "last_error": p["last_error"], "created_at": p["created_at"]}
            for p in pending_sessions
        ],
    }

@app.post("/api/sync/retry")
def sync_retry(central_server_url: str = "http://127.0.0.1:9000"):
    session_uploader = SessionUploader(central_server_url, _local_cache)
    patient_uploader = PatientSyncClient(central_server_url, _local_cache)
    return {
        "sessions": session_uploader.retry_pending(),
        "patients": patient_uploader.retry_pending(),
    }

@app.post("/api/sync/retry")
def sync_retry(central_server_url: str = "http://127.0.0.1:9000"):
    uploader = SessionUploader(central_server_url, _local_cache)
    return uploader.retry_pending()


_license_mgr_client = None  # not used directly here — activation goes through the central server, not local

def _get_hardware_fingerprint() -> str:
    """
    Stable-ish per-machine identifier. Not cryptographically bulletproof (MAC-based
    fingerprints can be spoofed), but sufficient for seat-counting against casual
    reuse rather than determined circumvention — matches the LAN-trust-level of
    everything else right now.
    """
    node = uuid_lib.getnode()
    return hashlib.sha256(f"{platform.system()}-{platform.node()}-{node}".encode()).hexdigest()

import hashlib  # add near top imports


class LicenseActivateRequest(BaseModel):
    license_key: str
    machine_label: str = platform.node()


@app.get("/api/license/status")
def license_status():
    state = _local_cache.get_state()
    if not state:
        return {"activated": False}

    valid_offline = _local_cache.is_valid_offline()

    # Try a live heartbeat if reachable; falls back to cached offline validity if not.
    try:
        r = http_requests.post(f"{_central_url()}/license/heartbeat",
                                data={"activation_id": state["activation_id"]}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            _local_cache.save(
                activation_id=state["activation_id"],
                license_key=state.get("license_key"),
                hardware_fingerprint=state.get("hardware_fingerprint"),
                license_id=state.get("license_id"),
                machine_label=state.get("machine_label"),
                server_expires_at=data.get("expires_at"),
            )
            return {"activated": True, "status": "active", "offline": False}
        else:
            _local_cache.mark_revoked()
            return {"activated": True, "status": "revoked", "offline": False}
    except http_requests.RequestException:
        if valid_offline:
            return {"activated": True, "status": "active", "offline": True}
        return {"activated": True, "status": "expired_offline_grace", "offline": True}


@app.post("/api/license/activate")
def license_activate(payload: LicenseActivateRequest):
    fingerprint = _get_hardware_fingerprint()
    try:
        r = http_requests.post(
            f"{_central_url()}/license/activate",
            data={
                "license_key": payload.license_key,
                "hardware_fingerprint": fingerprint,
                "machine_label": payload.machine_label,
                "os_platform": platform.system(),
                "app_version": "1.0.0",
            },
            timeout=10,
        )
    except http_requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", "activation_failed"))

    data = r.json()
    # Central server's /license/activate doesn't currently return license_id in its response body
    # (see LicenseManager.activate) — worth adding license_id to that return dict server-side so
    # it can be cached here for the uploader's license_id field. Flagging rather than papering over.
    _local_cache.save(
        activation_id=data["activation_id"],
        license_key=payload.license_key,
        hardware_fingerprint=fingerprint,
        machine_label=payload.machine_label,
        server_expires_at=data.get("expires_at"),
    )
    return {"ok": True}

class SceneUpdate(BaseModel):
    scene_id: float

class EventMarkerUpdate(BaseModel):
    value: float = 1.0

class HapticTrigger(BaseModel):
    side: str
    intensity: float
    duration_sec: float = 0.1

class TargetPosition(BaseModel):
    x: float
    y: float
    z: float

def _require_active_engine():
    if not active_engine or not getattr(active_engine, 'is_running', False):
        raise HTTPException(status_code=400, detail="No active recording session.")
    return active_engine

@app.post("/api/session/scene")
def set_scene(payload: SceneUpdate):
    _require_active_engine().live_state.set_scene(payload.scene_id)
    return {"ok": True}

@app.post("/api/session/mark")
def set_event_marker(payload: EventMarkerUpdate):
    _require_active_engine().live_state.set_event_marker(payload.value)
    return {"ok": True}

@app.post("/api/session/haptic")
def trigger_haptic(payload: HapticTrigger):
    if payload.side not in ("left", "right"):
        raise HTTPException(status_code=400, detail="side must be 'left' or 'right'")
    _require_active_engine().live_state.trigger_haptic(payload.side, payload.intensity, payload.duration_sec)
    return {"ok": True}

@app.post("/api/session/target")
def set_target_position(payload: TargetPosition):
    _require_active_engine().live_state.set_target_position(payload.x, payload.y, payload.z)
    return {"ok": True}

from src.patients.patient_manager import PatientManager
from src.core.exceptions import GDPRConsentError

_patients = PatientManager()

class PatientCreateRequest(BaseModel):
    display_name: str
    gdpr_consent_given: bool
    external_ref: str = ""
    date_of_birth: str = ""
    biological_sex: str = ""
    notes: str = ""

class PatientUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    external_ref: Optional[str] = None
    date_of_birth: Optional[str] = None
    biological_sex: Optional[str] = None
    notes: Optional[str] = None
    
@app.get("/api/patients")
def list_patients(include_anonymized: bool = False):
    return _patients.list_patients(include_anonymized=include_anonymized)
@app.post("/api/patients")
def create_patient(payload: PatientCreateRequest):
    try:
        patient = _patients.create_patient(
            display_name=payload.display_name,
            gdpr_consent_given=payload.gdpr_consent_given,
            external_ref=payload.external_ref,
            date_of_birth=payload.date_of_birth,
            biological_sex=payload.biological_sex,
            notes=payload.notes,
        )
    except GDPRConsentError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _patient_uploader.sync_patient(patient)
    return patient

@app.put("/api/patients/{patient_id}")
def update_patient(patient_id: str, payload: PatientUpdateRequest):
    try:
        updated = _patients.update_patient(
            patient_id, {k: v for k, v in payload.dict().items() if v is not None}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Patient not found")
    _patient_uploader.sync_patient(updated)
    return updated

@app.post("/api/patients/{patient_id}/withdraw-consent")
def withdraw_patient_consent(patient_id: str):
    updated = _patients.withdraw_consent(patient_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Patient not found")
    _patient_uploader.sync_patient(updated)
    return updated

@app.delete("/api/patients/{patient_id}")
def delete_patient(patient_id: str, hard_delete: bool = False):
    ok = _patients.delete_patient(patient_id, hard_delete=hard_delete)
    if not ok:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not hard_delete:
        # Push the now-anonymized record so central's copy reflects the erasure
        # instead of silently keeping the pre-erasure PII forever.
        anonymized = _patients.get_patient(patient_id)
        if anonymized:
            _patient_uploader.sync_patient(anonymized)
    return {"ok": True}

@app.get("/api/patients/{patient_id}/sessions")
def get_patient_sessions(patient_id: str):
    patient = _patients.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    from src.storage.database_manager import DatabaseManager
    db = DatabaseManager()
    return {
        "patient": patient,
        "sessions": db.get_sessions_for_patient(patient_id),
    }
from src.storage.patient_sync_client import PatientSyncClient

_patient_uploader = PatientSyncClient(_central_url(), _local_cache)
@app.on_event("startup")
def _sweep_pending_syncs_on_boot():
    # Anything that failed to reach central in a previous run gets one more
    # push attempt right away, same as the engine already does for sessions.
    try:
        _patient_uploader.retry_pending()
    except Exception as e:
        logger.warning(f"Patient sync sweep on boot failed: {e}")
  
# =====================================================================
# --- ORIGINAL CLI EXECUTION BLOCK ---
# =====================================================================

if __name__ == "__main__":
    execute_pipeline()