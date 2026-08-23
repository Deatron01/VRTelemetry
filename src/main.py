# src/main.py

import sys
import logging
import argparse
import threading
import sqlite3
import io
import pandas as pd
from typing import Dict, Any, Optional, List

# --- New API Imports ---
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.utils.logger import setup_logging, logger
from src.core.engine import TelemetryEngine
from src.backends.discovery import RuntimeCapabilityDiscovery
from src.core.exceptions import GDPRConsentError
from src.eye_tracking.factory import EyeTrackingFactory

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
    subject_id: str = "SUB_UNKN_01"
    backend: str = "auto"
    port: int = 5005
    gdpr_consent: bool
    output_dir: str = "Sessions"

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
                    session_id, start_timestamp_utc, subject_id, 
                    hmd_model, tracking_space_type, total_dropped_frames,
                    session_rating
                FROM session_metadata
                ORDER BY created_at DESC
            """)
            return cursor.fetchall()
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        
    logger.info(f"API Request: Start Pipeline -> Backend: [{config.backend.upper()}]")
    
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
        hardware_metadata=hardware_capabilities
    )
    
    active_engine.subject_metadata["M-IV_Static_Metadata"]["subject_id"] = config.subject_id
    active_engine.configured_backend = config.backend
    active_engine.network_port = config.port
        
    try:
        engine_thread = threading.Thread(target=run_engine_thread, args=(active_engine,), daemon=True)
        engine_thread.start()
        return {"status": "recording_started", "subject_id": config.subject_id, "backend": config.backend}
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
    elif hasattr(active_engine, 'is_running'):
        active_engine.is_running = False

    return {"status": "recording_stopped"}

# =====================================================================
# --- ORIGINAL CLI EXECUTION BLOCK ---
# =====================================================================

if __name__ == "__main__":
    execute_pipeline()