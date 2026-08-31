# src/main.py

import sys
import logging
import argparse
import threading
import sqlite3
import io
from pathlib import Path
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
    # Anthropometric calibration overrides (centimeters) — optional. When omitted,
    # _default_anthropometrics() derives a documented height-based estimate from
    # the patient's profile instead of silently persisting 0.0 like every session
    # recorded before this existed did.
    arm_length_left_cm: Optional[float] = None
    arm_length_right_cm: Optional[float] = None
    neutral_head_height_cm: Optional[float] = None
    shoulder_width_cm: Optional[float] = None

class SessionUpdate(BaseModel):
    subject_id: Optional[str] = None
    start_timestamp_utc: Optional[str] = None
    subject_vr_exp: Optional[str] = None
    session_rating: Optional[int] = None
    # Anthropometric/calibration fields — editable after the fact (meters/mm,
    # matching how they're stored — see _default_anthropometrics for the
    # centimeter<->meter conversion done at recording-start time).
    subject_ipd_mm: Optional[float] = None
    neutral_head_height: Optional[float] = None
    shoulder_width_est: Optional[float] = None
    arm_length_left: Optional[float] = None
    arm_length_right: Optional[float] = None
    dominant_hand: Optional[str] = None

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

@app.get("/api/sessions/{session_id}/telemetry")
def get_session_telemetry(session_id: str):
    """
    Lets Session Explorer load a previously recorded session's raw Parquet
    telemetry straight from disk for analysis — before this endpoint existed,
    every analysis page (Overview, Eye Tracking, Physiology, Research
    Insights, ...) only had data when the researcher manually drag-dropped a
    .parquet file via the header "Load Parquet" button; browsing to a session
    in Session Explorer and clicking into it never actually loaded its
    telemetry. Mirrors /api/upload-telemetry's downsampling so the frontend's
    existing TelemetryParser.processData() can consume either source identically.
    """
    row = _db_manager_for_sync.get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    parquet_path = Path(row.get("output_dir") or "Sessions") / f"vr_telemetry_{session_id}.parquet"
    if not parquet_path.exists():
        # output_dir isn't actually a stored column (sessions are always written under
        # the default "Sessions" root today) — fall back explicitly in case that ever changes.
        parquet_path = Path("Sessions") / f"vr_telemetry_{session_id}.parquet"
    if not parquet_path.exists():
        raise HTTPException(status_code=404, detail="Session recorded, but its Parquet file is missing on disk")

    df = pd.read_parquet(parquet_path)
    original_count = len(df)
    step = max(1, original_count // 60000)
    df_sampled = df.iloc[::step].copy()

    if 'timestamp_ns' in df_sampled.columns:
        first_ts = df['timestamp_ns'].iloc[0]
        df_sampled['timestamp_ns'] = df_sampled['timestamp_ns'] - first_ts

    df_sampled = df_sampled.where(pd.notnull(df_sampled), None)

    return {
        "original_frames": original_count,
        "columns": df.columns.tolist(),
        "frames": df_sampled.to_dict(orient="records"),
        "session_record": row,
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

class QuestionnaireSubmission(BaseModel):
    """
    Flat submission model for the post-session subjective questionnaire —
    16 SSQ symptom severities (0-3) and 6 NASA-TLX subscale ratings (0-100).
    All optional so a partially-completed form still submits something
    defensible rather than being all-or-nothing; src.analytics.questionnaires
    treats missing items as 0 and clamps out-of-range values.
    """
    # SSQ items (0-3)
    general_discomfort: Optional[int] = None
    fatigue: Optional[int] = None
    headache: Optional[int] = None
    eye_strain: Optional[int] = None
    difficulty_focusing: Optional[int] = None
    increased_salivation: Optional[int] = None
    sweating: Optional[int] = None
    nausea: Optional[int] = None
    difficulty_concentrating: Optional[int] = None
    fullness_of_head: Optional[int] = None
    blurred_vision: Optional[int] = None
    dizziness_eyes_open: Optional[int] = None
    dizziness_eyes_closed: Optional[int] = None
    vertigo: Optional[int] = None
    stomach_awareness: Optional[int] = None
    burping: Optional[int] = None
    # NASA-TLX items (0-100)
    mental_demand: Optional[float] = None
    physical_demand: Optional[float] = None
    temporal_demand: Optional[float] = None
    performance: Optional[float] = None
    effort: Optional[float] = None
    frustration: Optional[float] = None
    # Thermal comfort + free-form session context
    thermal_comfort: Optional[str] = None
    perceived_temp_c: Optional[float] = None
    session_rating: Optional[int] = None


@app.post("/api/sessions/{session_id}/questionnaire")
def submit_questionnaire(session_id: str, submission: QuestionnaireSubmission):
    """
    Scores and persists the post-session SSQ + NASA-TLX + thermal-comfort
    questionnaire for an already-recorded session, then best-effort re-syncs
    the updated metadata to the central server if this session was already
    uploaded (see SessionUploader.update_remote_metadata).
    """
    from datetime import datetime, timezone
    from src.analytics.questionnaires import score_ssq, score_nasa_tlx, is_valid_thermal_comfort, SSQ_ITEMS, NASA_TLX_ITEMS

    row = _db_manager_for_sync.get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    # A session linked to a patient whose GDPR consent has since been withdrawn
    # or erased must not accept new special-category health data either —
    # same rule as starting a new recording for that patient.
    patient_id = row.get("patient_id")
    if patient_id:
        patient = _patients.get_patient(patient_id)
        if patient and (patient["is_anonymized"] or not patient["gdpr_consent_given"]):
            raise HTTPException(
                status_code=403,
                detail="This session's patient record has withdrawn or erased GDPR consent; "
                       "new subjective/health data cannot be recorded against it.",
            )

    payload = submission.dict()
    ssq_scores = score_ssq({k: payload.get(k) for k in SSQ_ITEMS})
    tlx_scores = score_nasa_tlx({k: payload.get(k) for k in NASA_TLX_ITEMS})

    import json as _json
    fields: Dict[str, Any] = {
        "ssq_nausea_score": ssq_scores["ssq_nausea_score"],
        "ssq_oculomotor_score": ssq_scores["ssq_oculomotor_score"],
        "ssq_disorientation": ssq_scores["ssq_disorientation"],
        "ssq_total_severity": ssq_scores["ssq_total_severity"],
        "ssq_severity_band": ssq_scores["ssq_severity_band"],
        "ssq_raw_items_json": _json.dumps(ssq_scores["ssq_raw_items"]),
        "nasa_tlx_mental": tlx_scores["nasa_tlx_mental"],
        "nasa_tlx_physical": tlx_scores["nasa_tlx_physical"],
        "nasa_tlx_temporal": tlx_scores["nasa_tlx_temporal"],
        "nasa_tlx_performance": tlx_scores["nasa_tlx_performance"],
        "nasa_tlx_effort": tlx_scores["nasa_tlx_effort"],
        "nasa_tlx_frustration": tlx_scores["nasa_tlx_frustration"],
        "nasa_tlx_rtlx": tlx_scores["nasa_tlx_rtlx"],
        "nasa_tlx_band": tlx_scores["nasa_tlx_band"],
        "nasa_tlx_raw_items_json": _json.dumps({k: payload.get(k) for k in NASA_TLX_ITEMS}),
        "questionnaire_completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if submission.thermal_comfort and is_valid_thermal_comfort(submission.thermal_comfort):
        fields["thermal_comfort"] = submission.thermal_comfort
    if submission.perceived_temp_c is not None:
        fields["perceived_temp_c"] = submission.perceived_temp_c
    if submission.session_rating is not None:
        fields["session_rating"] = submission.session_rating

    saved = _db_manager_for_sync.save_subjective_questionnaire(session_id, fields)
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to persist questionnaire")

    # Best-effort push of the refreshed row to the central server. Never blocks
    # or fails the response — the local record is authoritative regardless.
    updated_row = _db_manager_for_sync.get_session_row(session_id)
    try:
        _session_uploader.update_remote_metadata(session_id, updated_row)
    except Exception as e:
        logger.info(f"Questionnaire saved locally; central re-sync skipped: {e}")

    return {"ok": True, "ssq": ssq_scores, "nasa_tlx": tlx_scores}


def _apply_patient_health_profile(engine: TelemetryEngine, patient: Dict[str, Any]) -> None:
    """
    Snapshots the patient's self-reported health/demographic profile into this
    session's own static metadata at the moment recording starts — the whole
    point of collecting it once on the Patient record instead of re-asking
    every session. DatabaseManager.session_metadata has always had columns for
    subject_age/height/weight/vr_exp/vision_*/dominant_hand; nothing populated
    them before this, so they silently defaulted to "Unknown"/0.0 for every
    session ever recorded. Snapshotting (rather than joining session_metadata
    to patients.patient_id live) means editing a patient's profile later never
    silently rewrites what an already-recorded session's covariates were.
    """
    static_meta = engine.subject_metadata.setdefault("M-IV_Static_Metadata", {})

    age = _patients.estimate_age_years(patient)
    if age is not None:
        static_meta["subject_age"] = age
    if patient.get("biological_sex"):
        static_meta["subject_biological_sex"] = patient["biological_sex"]
    if patient.get("height_cm") is not None:
        static_meta["subject_height_cm"] = patient["height_cm"]
    if patient.get("weight_kg") is not None:
        static_meta["subject_weight_kg"] = patient["weight_kg"]
    if patient.get("vr_experience_level"):
        static_meta["subject_vr_exp"] = patient["vr_experience_level"]
    if patient.get("vision_correction"):
        static_meta["vision_correction"] = patient["vision_correction"]
    if patient.get("vision_impairment"):
        static_meta["vision_impairment"] = patient["vision_impairment"]

    # dominant_hand is read from C-V_Calibration by DatabaseManager.persist_experiment,
    # not M-IV_Static_Metadata — a different bucket than the rest of these fields.
    if patient.get("dominant_hand"):
        calib_meta = engine.subject_metadata.setdefault("C-V_Calibration", {})
        calib_meta["dominant_hand"] = patient["dominant_hand"]

    # vr_experience_hours_estimate, gaming_experience_hours_per_week,
    # motion_sickness_susceptibility, and relevant_health_conditions have no
    # matching session_metadata column (they're patient-level traits, not
    # per-session measurements) — they stay on the Patient record and are
    # joined in at analysis time via session_metadata.patient_id, same as
    # age/height/weight would be if we hadn't chosen to snapshot those.


def _default_anthropometrics(height_cm: Optional[float]) -> Dict[str, float]:
    """
    Height-based anthropometric estimates used as an editable *default* when
    the researcher doesn't directly measure arm length / shoulder width /
    standing eye height for a subject. Ratios are the commonly cited
    Drillis & Contini (1966) body-segment-to-stature proportions used
    throughout biomechanics for exactly this "no direct measurement
    available" situation — not a substitute for a real measurement, but a
    documented, reproducible estimate instead of the silent 0.0 every
    session recorded before this pipeline existed got.
    Returned in meters, matching how HMD/controller positions are recorded.
    """
    if not height_cm or height_cm <= 0:
        return {}
    height_m = height_cm / 100.0
    return {
        "arm_length_left": round(height_m * 0.44, 4),
        "arm_length_right": round(height_m * 0.44, 4),
        "shoulder_width_est": round(height_m * 0.259, 4),
        "neutral_head_height": round(height_m * 0.93, 4),
    }


def _apply_calibration(engine: TelemetryEngine, patient: Dict[str, Any], config: "SessionStartConfig") -> None:
    """
    Populates C-V_Calibration with real (or best-effort-estimated) anthropometric
    baseline values instead of leaving neutral_head_height/shoulder_width_est/
    arm_length_left/right at persist_experiment's silent 0.0 default. These are
    the "necessary baseline variables to normalize physiological responses and
    calculate subject-specific kinematic reach constraints" — without them, every
    reach/kinematic metric downstream has nothing to normalize against.
    """
    calib_meta = engine.subject_metadata.setdefault("C-V_Calibration", {})

    defaults = _default_anthropometrics(patient.get("height_cm"))
    calib_meta.update(defaults)  # estimated baseline first...

    # ...then apply any researcher-entered measurement, which always wins over the estimate.
    if config.arm_length_left_cm is not None:
        calib_meta["arm_length_left"] = round(config.arm_length_left_cm / 100.0, 4)
    if config.arm_length_right_cm is not None:
        calib_meta["arm_length_right"] = round(config.arm_length_right_cm / 100.0, 4)
    if config.neutral_head_height_cm is not None:
        calib_meta["neutral_head_height"] = round(config.neutral_head_height_cm / 100.0, 4)
    if config.shoulder_width_cm is not None:
        calib_meta["shoulder_width_est"] = round(config.shoulder_width_cm / 100.0, 4)


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
    _apply_patient_health_profile(active_engine, patient)
    _apply_calibration(active_engine, patient, config)
    active_engine.configured_backend = config.backend
    active_engine.network_port = config.port

    try:
        engine_thread = threading.Thread(target=run_engine_thread, args=(active_engine,), daemon=True)
        engine_thread.start()
        _usage.log_event("recording_start", detail=f"backend={config.backend}, patient={patient['patient_id']}")
        return {"status": "recording_started", "patient_id": patient["patient_id"], "backend": config.backend, "session_id": active_engine.session_id}
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

# Persistent uploader used by the background sync scheduler and the manual
# 'Sync Now' endpoint alike, so both paths share one retry/backoff history
# instead of the ad-hoc per-request instances the old code constructed.
_session_uploader = SessionUploader(_central_url(), _local_cache)


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
    pending_logs = _local_cache.list_pending_session_logs()
    pending_patients = _local_cache.list_pending_patient_syncs()
    return {
        "pending_count": len(pending_sessions) + len(pending_logs) + len(pending_patients),
        "pending_sessions": len(pending_sessions),
        "pending_logs": len(pending_logs),
        "pending_patients": len(pending_patients),
        "background_sync_running": bool(_sync_scheduler._thread and _sync_scheduler._thread.is_alive()),
        "heartbeat_running": bool(_heartbeat_sender._thread and _heartbeat_sender._thread.is_alive()),
        "pending": [
            {"session_id": p["session_id"], "attempts": p["attempts"], "last_error": p["last_error"], "created_at": p["created_at"]}
            for p in pending_sessions
        ],
        "pending_log_items": [
            {"session_id": p["session_id"], "attempts": p["attempts"], "last_error": p["last_error"], "created_at": p["created_at"]}
            for p in pending_logs
        ],
        "pending_patient_items": [
            {"patient_id": p["patient_id"], "attempts": p["attempts"], "last_error": p["last_error"], "created_at": p["created_at"]}
            for p in pending_patients
        ],
    }

@app.post("/api/sync/retry")
def sync_retry():
    """
    Manual 'Sync Now' action. Runs the exact same sweep the background
    scheduler runs automatically every ~20s (sessions, session logs, then
    patients) — this button just forces an out-of-schedule pass, it doesn't
    do anything the background loop wasn't already going to do shortly.
    """
    return _sync_scheduler.sweep_once()


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
                                data={"activation_id": state["activation_id"],
                                      "machine_label": state.get("machine_label") or ""}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            _local_cache.save(
                activation_id=state["activation_id"],
                license_key=state.get("license_key"),
                hardware_fingerprint=state.get("hardware_fingerprint"),
                # Prefer whatever license_id the server just handed back — this is
                # what lets an install stuck with a missing license_id (see the
                # activation bug fixed below) self-heal on the next poll instead
                # of staying broken until the researcher reactivates by hand.
                license_id=data.get("license_id") or state.get("license_id"),
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
    _local_cache.save(
        activation_id=data["activation_id"],
        license_key=payload.license_key,
        hardware_fingerprint=fingerprint,
        license_id=data.get("license_id"),
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
    # Self-reported health/demographic profile — see PatientManager.HEALTH_PROFILE_FIELDS.
    # Collected once here rather than re-asked on every recording session; the values
    # get snapshotted into each session's own metadata row at recording time.
    age_years: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    dominant_hand: str = ""
    vr_experience_level: str = ""
    vr_experience_hours_estimate: Optional[float] = None
    gaming_experience_hours_per_week: Optional[float] = None
    vision_correction: str = ""
    vision_impairment: str = ""
    motion_sickness_susceptibility: str = ""
    relevant_health_conditions: str = ""

class PatientUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    external_ref: Optional[str] = None
    date_of_birth: Optional[str] = None
    biological_sex: Optional[str] = None
    notes: Optional[str] = None
    age_years: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    dominant_hand: Optional[str] = None
    vr_experience_level: Optional[str] = None
    vr_experience_hours_estimate: Optional[float] = None
    gaming_experience_hours_per_week: Optional[float] = None
    vision_correction: Optional[str] = None
    vision_impairment: Optional[str] = None
    motion_sickness_susceptibility: Optional[str] = None
    relevant_health_conditions: Optional[str] = None
    
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
            age_years=payload.age_years,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
            dominant_hand=payload.dominant_hand,
            vr_experience_level=payload.vr_experience_level,
            vr_experience_hours_estimate=payload.vr_experience_hours_estimate,
            gaming_experience_hours_per_week=payload.gaming_experience_hours_per_week,
            vision_correction=payload.vision_correction,
            vision_impairment=payload.vision_impairment,
            motion_sickness_susceptibility=payload.motion_sickness_susceptibility,
            relevant_health_conditions=payload.relevant_health_conditions,
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
from src.storage.sync_scheduler import BackgroundSyncScheduler
from src.storage.heartbeat_client import HeartbeatSender
from src.storage.session_backfill import backfill_unsynced_sessions
from src.storage.database_manager import DatabaseManager

_patient_uploader = PatientSyncClient(_central_url(), _local_cache)

# Shared DatabaseManager instance (vr_metadata.db) for the historical backfill
# sweep below — the metadata rows for every session ever recorded locally
# live here, independent of whether a sync attempt was ever made for them.
_db_manager_for_sync = DatabaseManager()

# Must match TelemetryEngine's/argparse's own defaults ("Sessions") — this is
# where session_uploader.upload() expects to find vr_telemetry_<id>.parquet
# and where attach_session_log_capture() writes session_<id>.log.
_SESSIONS_OUTPUT_DIR = "Sessions"
_SESSIONS_LOG_DIR = "Sessions/logs"


def _repair_missing_license_id() -> None:
    """
    Self-heal for installs already stuck with license_id=None in the local
    cache — a pre-existing bug where /api/license/activate never forwarded
    the license_id the central server's /license/activate response already
    included. Every session/log/patient upload has a *required* license_id
    form field server-side, so a machine in this state 422's on every single
    upload attempt until it re-activates or this repair runs. Safe to call on
    every boot: it's a no-op the instant license_id is already populated.
    """
    state = _local_cache.get_state()
    if not state or state.get("license_id") or not state.get("activation_id"):
        return
    try:
        r = http_requests.post(
            f"{_central_url()}/license/heartbeat",
            data={"activation_id": state["activation_id"], "machine_label": state.get("machine_label") or ""},
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning(f"license_id repair: heartbeat rejected ({r.status_code}), leaving as-is for now.")
            return
        license_id = r.json().get("license_id")
        if not license_id:
            logger.warning("license_id repair: server heartbeat didn't return a license_id either — "
                            "uploads will keep failing until this activation is investigated.")
            return
        _local_cache.save(
            activation_id=state["activation_id"],
            license_key=state.get("license_key"),
            hardware_fingerprint=state.get("hardware_fingerprint"),
            license_id=license_id,
            machine_label=state.get("machine_label"),
            server_expires_at=state.get("server_expires_at"),
        )
        logger.info(f"Repaired missing license_id in local cache ({license_id}) — uploads should work now.")
    except http_requests.RequestException as e:
        logger.debug(f"license_id repair skipped — central server unreachable: {e}")


def _run_session_backfill() -> Dict[str, Any]:
    """
    Requirement: "every already-recorded telemetry session that isn't on the
    central server yet should get uploaded too." BackgroundSyncScheduler only
    retries what's already sitting in the pending_uploads/pending_session_logs
    queues — a session recorded before that plumbing existed (or one whose
    very first upload attempt was never made at all, e.g. the app crashed
    before reaching _upload_completed_session) never entered those queues in
    the first place, so it would otherwise sit unsynced forever. This scans
    every session session_metadata.db knows about and closes that gap.
    """
    try:
        return backfill_unsynced_sessions(
            output_dir=_SESSIONS_OUTPUT_DIR,
            db_manager=_db_manager_for_sync,
            session_uploader=_session_uploader,
            local_license_cache=_local_cache,
            log_dir=_SESSIONS_LOG_DIR,
        )
    except Exception as e:
        logger.warning(f"Historical session backfill sweep failed: {e}")
        return {"error": str(e)}


@app.post("/api/sync/backfill")
def sync_backfill():
    """
    Manual trigger for the historical backfill sweep — same scan the app runs
    once automatically on startup, exposed here in case a researcher wants to
    force a rescan (e.g. after restoring an old Sessions/ folder) without
    restarting the whole app.
    """
    return _run_session_backfill()

# --- Automatic background sync (Requirement 1) ---
# Sweeps pending sessions/logs/patients on a timer for as long as this backend
# process is alive — i.e. for as long as the desktop app is open — regardless
# of whether a recording is active or anyone is looking at the UI.
_sync_scheduler = BackgroundSyncScheduler(_session_uploader, _patient_uploader, interval_sec=20.0)

# --- Client heartbeat (Requirement 2) ---
# Pings the central server every 30s with this machine's activation_id and
# machine_label so the Admin "Active Clients" tab can show live online/offline
# status. Reports current engine state and outstanding sync backlog too, since
# the server already has a place to store it and the admin view can use it.
def _current_client_status() -> str:
    return "recording" if (active_engine and getattr(active_engine, "is_running", False)) else "idle"

def _current_pending_count() -> int:
    try:
        return (
            len(_local_cache.list_pending_uploads())
            + len(_local_cache.list_pending_session_logs())
            + len(_local_cache.list_pending_patient_syncs())
        )
    except Exception:
        return 0

_heartbeat_sender = HeartbeatSender(
    central_server_url_provider=_central_url,
    local_license_cache=_local_cache,
    interval_sec=30.0,
    status_provider=_current_client_status,
    pending_count_provider=_current_pending_count,
)


@app.on_event("startup")
def _start_background_sync_and_heartbeat():
    # Immediate sweep on boot (covers what the old code only did for patients),
    # then hand off to the periodic scheduler + heartbeat loop for the rest of
    # the process's lifetime.
    try:
        _repair_missing_license_id()
    except Exception as e:
        logger.warning(f"license_id repair on boot failed: {e}")
    try:
        _run_session_backfill()
    except Exception as e:
        logger.warning(f"Session backfill sweep on boot failed: {e}")
    try:
        _sync_scheduler.sweep_once()
    except Exception as e:
        logger.warning(f"Initial sync sweep on boot failed: {e}")
    _sync_scheduler.start()
    _heartbeat_sender.start()


@app.on_event("shutdown")
def _stop_background_sync_and_heartbeat():
    _sync_scheduler.stop()
    _heartbeat_sender.stop()

# =====================================================================
# --- ORIGINAL CLI EXECUTION BLOCK ---
# =====================================================================

if __name__ == "__main__":
    execute_pipeline()