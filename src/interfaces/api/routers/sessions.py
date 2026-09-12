# src/interfaces/api/routers/sessions.py
"""Session listing, detail, update and raw telemetry.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.interfaces.api.dependencies import AVRecordingsDep, PatientsDep, SessionsDep, SettingsDep
from src.interfaces.api.schemas.sessions import SessionUpdate

router = APIRouter(tags=["sessions"])


@router.post("/api/upload-telemetry")
async def upload_telemetry(settings: SettingsDep, file: UploadFile = File(...)):
    """
    Fogadja a nagyméretű Parquet fájlt, és memóriahatékonyan feldolgozza Pandas segítségével.
    """
    content = await file.read()

    # A Pandas nagyságrendekkel memóriahatékonyabb a Parquet olvasásában
    df = pd.read_parquet(io.BytesIO(content))
    original_count = len(df)

    # Ritkítás (Downsampling) max 60,000 sorra a React stabil működéséhez
    step = max(1, original_count // settings.sync.max_frames_to_client)
    df_sampled = df.iloc[::step].copy()

    # 1. JAVÍTÁS: Nanosecond Timestamp túlcsordulás megelőzése JS-ben
    # Levonjuk az első frame idejét mindenből, így hatalmas, memóriagyilkos számok
    # helyett 0-ról induló másodperceket kap a React.
    if "timestamp_ns" in df_sampled.columns and original_count > 0:
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
def get_session_telemetry(session_id: str, sessions: SessionsDep, settings: SettingsDep):
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
    row = sessions.get(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    sessions_dir = settings.paths.sessions_dir
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
    step = max(1, original_count // settings.sync.max_frames_to_client)
    df_sampled = df.iloc[::step].copy()

    if "timestamp_ns" in df_sampled.columns and original_count > 0:
        # A session that recorded zero frames (crashed before its first
        # frame, or was stopped immediately) leaves an empty Parquet file --
        # df_sampled is then also empty, and indexing .iloc[0] into it raised
        # IndexError instead of just returning "no frames" like the rest of
        # this response already does gracefully via original_frames == 0.
        first_ts = df["timestamp_ns"].iloc[0]
        df_sampled["timestamp_ns"] = df_sampled["timestamp_ns"] - first_ts

    df_sampled = df_sampled.where(pd.notnull(df_sampled), None)

    return {
        "original_frames": original_count,
        "columns": df.columns.tolist(),
        "frames": df_sampled.to_dict(orient="records"),
        "session_record": row,
    }


@router.get("/api/sessions/{session_id}/av-recording")
def get_session_av_recording(
    session_id: str, sessions: SessionsDep, av_recordings: AVRecordingsDep
):
    """A session's A/V recording (P-C7) metadata: whether it has a video and
    a transcript, and -- Art. 5(1)(e) storage limitation -- whether the raw
    video has already been erased by the retention sweep while a verified
    transcript was kept. Deliberately not the raw ``av_recordings`` row:
    ``video_path``/``transcript_path`` are local filesystem paths, useful to
    the two download routes below but not to a frontend that only needs to
    know what is available to show.
    """
    if not sessions.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    row = av_recordings.get(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="No A/V recording for this session")

    video_erased = row["raw_recording_deleted_at_utc"] is not None
    return {
        "session_id": row["session_id"],
        "capture_backend": row["capture_backend"],
        "started_at_utc": row["started_at_utc"],
        "ended_at_utc": row["ended_at_utc"],
        "has_video": bool(row["video_path"]) and not video_erased,
        "video_deleted_at_utc": row["raw_recording_deleted_at_utc"],
        "has_transcript": bool(row["transcript_path"]),
        "transcript_verified": bool(row["transcript_verified"]),
        "transcript_engine": row["transcript_engine"],
        "failure_reason": row["failure_reason"],
    }


@router.get("/api/sessions/{session_id}/av-recording/video")
def get_session_av_recording_video(session_id: str, av_recordings: AVRecordingsDep):
    """Streams the session's captured video file for playback/download.

    410 (not 404) when the video specifically has been removed by the
    retention sweep -- Art. 5(1)(e) storage limitation acting as designed,
    not a missing/broken file, and a researcher following a link from an
    older report should see the difference.
    """
    row = av_recordings.get(session_id)
    if not row or not row["video_path"]:
        raise HTTPException(status_code=404, detail="No video recorded for this session")
    if row["raw_recording_deleted_at_utc"] is not None:
        raise HTTPException(
            status_code=410,
            detail=(
                "This session's raw video has been deleted under the configured "
                "retention period (GDPR Art. 5(1)(e)); its transcript may still be "
                "available."
            ),
        )

    video_path = Path(row["video_path"])
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file is missing on disk")
    return FileResponse(video_path, filename=video_path.name, media_type="video/mp4")


@router.get("/api/sessions/{session_id}/av-recording/transcript")
def get_session_av_recording_transcript(session_id: str, av_recordings: AVRecordingsDep):
    """Returns the session's transcript (``Transcript.as_dict()``, written by
    ``WhisperTranscriber``/``SessionRecorder``) as JSON -- kept even after
    the raw video is erased under retention, since it is the durable research
    artifact the video capture exists to produce.
    """
    row = av_recordings.get(session_id)
    if not row or not row["transcript_path"]:
        raise HTTPException(status_code=404, detail="No transcript available for this session")

    transcript_path = Path(row["transcript_path"])
    if not transcript_path.exists():
        raise HTTPException(status_code=404, detail="Transcript file is missing on disk")
    return json.loads(transcript_path.read_text(encoding="utf-8"))


@router.get("/api/sessions")
def get_all_sessions(sessions: SessionsDep, patients: PatientsDep):
    rows = sessions.list_for_api()

    # Enrich with patient display names. Sessions recorded before patient
    # linking existed (or where the patient was since erased) fall back
    # gracefully rather than breaking the listing.
    patient_cache: dict[str, str | None] = {}
    for s in rows:
        pid = s.get("patient_id")
        if not pid:
            s["patient_display_name"] = None
            continue
        if pid not in patient_cache:
            p = patients.get_patient(pid)
            patient_cache[pid] = (
                p["display_name"]
                if p and not p["is_anonymized"]
                else "[Erased Patient]"
                if p
                else None
            )
        s["patient_display_name"] = patient_cache[pid]

    return rows


@router.get("/api/sessions/{session_id}")
def get_session_details(session_id: str, sessions: SessionsDep):
    row = sessions.get(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


@router.put("/api/sessions/{session_id}")
def update_session(session_id: str, update_data: SessionUpdate, sessions: SessionsDep):
    update_fields = {k: v for k, v in update_data.dict().items() if v is not None}
    if not update_fields:
        return {"status": "no changes"}

    updated, written = sessions.update(session_id, update_fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"status": "success", "updated_fields": written}
