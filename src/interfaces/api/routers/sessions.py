# src/interfaces/api/routers/sessions.py
"""Session listing, detail, update and raw telemetry.

Moved from src/main.py. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile

from src.config import get_settings
from src.interfaces.api import dependencies as deps
from src.interfaces.api.schemas.sessions import SessionUpdate

router = APIRouter(tags=["sessions"])


@router.post("/api/upload-telemetry")
async def upload_telemetry(file: UploadFile = File(...)):
    """
    Fogadja a nagyméretű Parquet fájlt, és memóriahatékonyan feldolgozza Pandas segítségével.
    """
    content = await file.read()

    # A Pandas nagyságrendekkel memóriahatékonyabb a Parquet olvasásában
    df = pd.read_parquet(io.BytesIO(content))
    original_count = len(df)

    # Ritkítás (Downsampling) max 60,000 sorra a React stabil működéséhez
    step = max(1, original_count // get_settings().sync.max_frames_to_client)
    df_sampled = df.iloc[::step].copy()

    # 1. JAVÍTÁS: Nanosecond Timestamp túlcsordulás megelőzése JS-ben
    # Levonjuk az első frame idejét mindenből, így hatalmas, memóriagyilkos számok
    # helyett 0-ról induló másodperceket kap a React.
    if "timestamp_ns" in df_sampled.columns:
        first_ts = df["timestamp_ns"].iloc[0]
        df_sampled["timestamp_ns"] = df_sampled["timestamp_ns"] - first_ts

    # 2. JAVÍTÁS: Kvaterniók (3D forgatás) megmentése
    # A korábbi fillna(0) a hiányzó w értékeket 0-ra állította, ami Three.js NaN összeomlást okozott.
    # Ez a sor a hiányzó adatokat szigorúan `null`-ként küldi át a JSON-ben, így a
    # React biztonsági fallbackje (pl. `f.left_eye_rot_w ?? 1`) végre tud aktiválódni!
    df_sampled = df_sampled.where(pd.notnull(df_sampled), None)

    return {
        "original_frames": original_count,
        "columns": df.columns.tolist(),
        "frames": df_sampled.to_dict(orient="records"),
    }


@router.get("/api/sessions/{session_id}/telemetry")
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
    row = deps.db_manager.get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    sessions_dir = get_settings().paths.sessions_dir
    parquet_path = (
        Path(row.get("output_dir") or sessions_dir) / f"vr_telemetry_{session_id}.parquet"
    )
    if not parquet_path.exists():
        # output_dir isn't actually a stored column (sessions are always written under
        # the configured sessions root today) - fall back explicitly in case that changes.
        parquet_path = sessions_dir / f"vr_telemetry_{session_id}.parquet"
    if not parquet_path.exists():
        raise HTTPException(
            status_code=404, detail="Session recorded, but its Parquet file is missing on disk"
        )

    df = pd.read_parquet(parquet_path)
    original_count = len(df)
    step = max(1, original_count // get_settings().sync.max_frames_to_client)
    df_sampled = df.iloc[::step].copy()

    if "timestamp_ns" in df_sampled.columns:
        first_ts = df["timestamp_ns"].iloc[0]
        df_sampled["timestamp_ns"] = df_sampled["timestamp_ns"] - first_ts

    df_sampled = df_sampled.where(pd.notnull(df_sampled), None)

    return {
        "original_frames": original_count,
        "columns": df.columns.tolist(),
        "frames": df_sampled.to_dict(orient="records"),
        "session_record": row,
    }


@router.get("/api/sessions")
def get_all_sessions():
    try:
        with sqlite3.connect(deps.db_path()) as conn:
            conn.row_factory = deps.dict_factory
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
    patient_cache: dict[str, str | None] = {}
    for s in sessions:
        pid = s.get("patient_id")
        if not pid:
            s["patient_display_name"] = None
            continue
        if pid not in patient_cache:
            p = deps.patients.get_patient(pid)
            patient_cache[pid] = (
                p["display_name"]
                if p and not p["is_anonymized"]
                else "[Erased Patient]"
                if p
                else None
            )
        s["patient_display_name"] = patient_cache[pid]

    return sessions


@router.get("/api/sessions/{session_id}")
def get_session_details(session_id: str):
    try:
        with sqlite3.connect(deps.db_path()) as conn:
            conn.row_factory = deps.dict_factory
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM session_metadata WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")
            return row
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/sessions/{session_id}")
def update_session(session_id: str, update_data: SessionUpdate):
    try:
        with sqlite3.connect(deps.db_path()) as conn:
            cursor = conn.cursor()
            update_fields = {k: v for k, v in update_data.dict().items() if v is not None}
            if not update_fields:
                return {"status": "no changes"}

            set_clause = ", ".join([f"{k} = ?" for k in update_fields])
            values = list(update_fields.values())
            values.append(session_id)

            cursor.execute(f"UPDATE session_metadata SET {set_clause} WHERE session_id = ?", values)
            conn.commit()

            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Session not found")

            return {"status": "success", "updated_fields": list(update_fields.keys())}
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))
