# src/interfaces/api/routers/sync.py
"""Upload queue status, manual retry and the historical backfill.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from src.interfaces.api.dependencies import (
    ContainerDep,
    HeartbeatDep,
    LocalCacheDep,
    SyncSchedulerDep,
)
from src.storage.session_backfill import backfill_unsynced_sessions
from src.utils.logger import logger

if TYPE_CHECKING:
    from src.interfaces.api.container import Container

router = APIRouter(tags=["sync"])


@router.get("/api/sync/status")
def sync_status(
    local_cache: LocalCacheDep,
    sync_scheduler: SyncSchedulerDep,
    heartbeat_sender: HeartbeatDep,
):
    pending_sessions = local_cache.list_pending_uploads()
    pending_logs = local_cache.list_pending_session_logs()
    pending_patients = local_cache.list_pending_patient_syncs()
    return {
        "pending_count": len(pending_sessions) + len(pending_logs) + len(pending_patients),
        "pending_sessions": len(pending_sessions),
        "pending_logs": len(pending_logs),
        "pending_patients": len(pending_patients),
        # `is_running` rather than reaching into `._thread`: whether a loop is
        # alive is the loop's own business, and this route asserting otherwise
        # is how a private attribute rename becomes a 500 in the admin UI.
        "background_sync_running": sync_scheduler.is_running,
        "heartbeat_running": heartbeat_sender.is_running,
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
def sync_retry(sync_scheduler: SyncSchedulerDep):
    """
    Manual 'Sync Now' action. Runs the exact same sweep the background
    scheduler runs automatically every ~20s (sessions, session logs, then
    patients) — this button just forces an out-of-schedule pass, it doesn't
    do anything the background loop wasn't already going to do shortly.
    """
    return sync_scheduler.sweep_once()


def run_session_backfill(container: Container) -> dict[str, Any]:
    """
    Requirement: "every already-recorded telemetry session that isn't on the
    central server yet should get uploaded too." BackgroundSyncScheduler only
    retries what's already sitting in the pending_uploads/pending_session_logs
    queues — a session recorded before that plumbing existed (or one whose
    very first upload attempt was never made at all, e.g. the app crashed
    before reaching _upload_completed_session) never entered those queues in
    the first place, so it would otherwise sit unsynced forever. This scans
    every session session_metadata.db knows about and closes that gap.

    Takes the container rather than reading module-level singletons, because it
    runs from two places: the application's lifespan, where there is no request
    to resolve ``Depends`` against, and the route below, where there is.

    Args:
        container: The collaborators of the application running the sweep.

    Returns:
        The backfill summary, or ``{"error": ...}`` — a sweep that fails must
        not take the boot sequence or the request down with it.
    """
    try:
        return backfill_unsynced_sessions(
            output_dir=container.sessions_output_dir,
            db_manager=container.db_manager,
            session_uploader=container.session_uploader,
            local_license_cache=container.local_cache,
            log_dir=container.sessions_log_dir,
        )
    except Exception as e:  # noqa: BLE001 - documented above: a sweep must not take boot or the request down
        # Broad because this runs from the lifespan, where an exception aborts
        # application startup entirely, and the sweep is an optimisation: every
        # session it would have queued is still on disk and still found by the
        # next sweep. The failure is returned to the caller rather than hidden,
        # which is what makes this a report rather than a swallow.
        logger.warning(f"Historical session backfill sweep failed: {e}", exc_info=True)
        return {"error": str(e)}


@router.post("/api/sync/backfill")
def sync_backfill(container: ContainerDep):
    """
    Manual trigger for the historical backfill sweep — same scan the app runs
    once automatically on startup, exposed here in case a researcher wants to
    force a rescan (e.g. after restoring an old Sessions/ folder) without
    restarting the whole app.
    """
    return run_session_backfill(container)
