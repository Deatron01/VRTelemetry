# src/interfaces/api/routers/sync.py
"""Upload queue status, manual retry and the historical backfill.

Moved from src/main.py. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.interfaces.api import dependencies as deps
from src.storage.session_backfill import backfill_unsynced_sessions
from src.utils.logger import logger

router = APIRouter(tags=["sync"])


@router.get("/api/sync/status")
def sync_status():
    pending_sessions = deps.local_cache.list_pending_uploads()
    pending_logs = deps.local_cache.list_pending_session_logs()
    pending_patients = deps.local_cache.list_pending_patient_syncs()
    return {
        "pending_count": len(pending_sessions) + len(pending_logs) + len(pending_patients),
        "pending_sessions": len(pending_sessions),
        "pending_logs": len(pending_logs),
        "pending_patients": len(pending_patients),
        "background_sync_running": bool(
            deps.sync_scheduler._thread and deps.sync_scheduler._thread.is_alive()
        ),
        "heartbeat_running": bool(
            deps.heartbeat_sender._thread and deps.heartbeat_sender._thread.is_alive()
        ),
        "pending": [
            {
                "session_id": p["session_id"],
                "attempts": p["attempts"],
                "last_error": p["last_error"],
                "created_at": p["created_at"],
            }
            for p in pending_sessions
        ],
        "pending_log_items": [
            {
                "session_id": p["session_id"],
                "attempts": p["attempts"],
                "last_error": p["last_error"],
                "created_at": p["created_at"],
            }
            for p in pending_logs
        ],
        "pending_patient_items": [
            {
                "patient_id": p["patient_id"],
                "attempts": p["attempts"],
                "last_error": p["last_error"],
                "created_at": p["created_at"],
            }
            for p in pending_patients
        ],
    }


@router.post("/api/sync/retry")
def sync_retry():
    """
    Manual 'Sync Now' action. Runs the exact same sweep the background
    scheduler runs automatically every ~20s (sessions, session logs, then
    patients) — this button just forces an out-of-schedule pass, it doesn't
    do anything the background loop wasn't already going to do shortly.
    """
    return deps.sync_scheduler.sweep_once()


def run_session_backfill() -> dict[str, Any]:
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
            output_dir=deps.sessions_output_dir,
            db_manager=deps.db_manager,
            session_uploader=deps.session_uploader,
            local_license_cache=deps.local_cache,
            log_dir=deps.sessions_log_dir,
        )
    except Exception as e:
        logger.warning(f"Historical session backfill sweep failed: {e}")
        return {"error": str(e)}


@router.post("/api/sync/backfill")
def sync_backfill():
    """
    Manual trigger for the historical backfill sweep — same scan the app runs
    once automatically on startup, exposed here in case a researcher wants to
    force a rescan (e.g. after restoring an old Sessions/ folder) without
    restarting the whole app.
    """
    return run_session_backfill()
