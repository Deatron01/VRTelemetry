# src/storage/session_backfill.py

"""
Historical reconciliation sweep: finds telemetry sessions (and their logs)
that were recorded on this machine at some point but never made it to the
central server — because they predate the sync/queue plumbing entirely, were
recorded while offline and the app was closed before a retry could happen, or
any other gap where nothing ever called SessionUploader.upload() for them in
the first place. Without this, such a session sits on disk forever: it was
never queued, so BackgroundSyncScheduler's periodic sweep has nothing to pick
up (that sweep only retries what's already IN pending_uploads/pending_session
_logs).

Two independent sources of truth are combined here, not just one:

1. session_metadata.db (via DatabaseManager.list_all_sessions()) — the normal
   case, gives real subject/patient linkage for a session.
2. A direct filesystem scan of the Sessions output/log directories for
   vr_telemetry_<id>.parquet / session_<id>.log files.

(2) matters because a recording can leave a Parquet file (and/or a log) on
disk without ever getting a session_metadata row — e.g. persist_experiment()
failing partway, or an interrupted run — and relying on the metadata DB alone
would silently skip that file forever. This module treats "a Parquet file
exists on disk" as the ground truth for "a session exists", and metadata-DB
rows purely as an optional enrichment (subject_id/patient_id) layered on top.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PARQUET_PREFIX = "vr_telemetry_"
PARQUET_SUFFIX = ".parquet"
LOG_PREFIX = "session_"
LOG_SUFFIX = ".log"


def _try_get_parquet_row_count(parquet_path: Path) -> Optional[int]:
    """
    Reads only the Parquet file's footer metadata (row count), not the actual
    column data — cheap even for a large file, and gives backfilled sessions a
    real total_frames instead of leaving it null forever (session_metadata.db
    doesn't store a frame count; that only ever existed in engine memory).
    """
    try:
        import pyarrow.parquet as pq
        return pq.ParquetFile(str(parquet_path)).metadata.num_rows
    except Exception as e:
        logger.debug(f"Could not read Parquet row count for {parquet_path}: {e}")
        return None


def _scan_session_ids(directory: Path, prefix: str, suffix: str) -> Dict[str, Path]:
    """Maps session_id -> file path for every file in `directory` matching prefix/suffix."""
    found: Dict[str, Path] = {}
    if not directory.exists():
        return found
    for path in directory.glob(f"{prefix}*{suffix}"):
        if not path.is_file():
            continue
        name = path.name
        session_id = name[len(prefix):-len(suffix)] if suffix else name[len(prefix):]
        if session_id:
            found[session_id] = path
    return found


def backfill_unsynced_sessions(
    *,
    output_dir: str,
    db_manager,
    session_uploader,
    local_license_cache,
    log_dir: str = "Sessions/logs",
) -> Dict[str, Any]:
    """
    One reconciliation pass. Safe to call repeatedly (e.g. on every app boot,
    or from a manual 'Backfill now' action) — sessions already confirmed
    synced, or already sitting in a pending queue that the background
    scheduler is already retrying, are skipped without touching the network.
    """
    summary = {
        "sessions_found": 0,
        "sessions_already_synced": 0,
        "sessions_already_queued": 0,
        "sessions_missing_file": 0,
        "sessions_uploaded_now": 0,
        "sessions_queued_now": 0,
        "sessions_without_metadata_row": 0,  # orphan Parquet files backfilled with minimal metadata
        "logs_uploaded_now": 0,
        "logs_queued_now": 0,
    }

    output_path = Path(output_dir)
    log_path_dir = Path(log_dir)

    try:
        metadata_rows = {row["session_id"]: row for row in db_manager.list_all_sessions() if row.get("session_id")}
    except Exception as e:
        logger.error(f"Backfill sweep aborted — could not list local sessions: {e}")
        return summary

    parquet_files = _scan_session_ids(output_path, PARQUET_PREFIX, PARQUET_SUFFIX)
    log_files = _scan_session_ids(log_path_dir, LOG_PREFIX, LOG_SUFFIX)

    all_session_ids = set(metadata_rows) | set(parquet_files) | set(log_files)
    summary["sessions_found"] = len(all_session_ids)
    if not all_session_ids:
        return summary

    already_pending_ids = {item["session_id"] for item in local_license_cache.list_pending_uploads()}
    already_pending_log_ids = {item["session_id"] for item in local_license_cache.list_pending_session_logs()}

    for session_id in sorted(all_session_ids):
        row = metadata_rows.get(session_id)
        parquet_path = parquet_files.get(session_id)

        # --- Parquet telemetry file ---
        if local_license_cache.is_session_synced(session_id):
            summary["sessions_already_synced"] += 1
        elif session_id in already_pending_ids:
            # Already known to the sync system and being retried on schedule —
            # don't fire a second, racing upload attempt for the same file.
            summary["sessions_already_queued"] += 1
        elif not parquet_path or not parquet_path.exists():
            # Either a metadata row with no matching file on disk (e.g. a stale
            # test/manual row), or a session that only ever produced a log.
            summary["sessions_missing_file"] += 1
        else:
            if row is None:
                summary["sessions_without_metadata_row"] += 1
                logger.warning(
                    f"Backfill: {parquet_path.name} has no session_metadata row (subject/patient "
                    f"linkage unknown) — uploading with minimal metadata rather than skipping it."
                )
            metadata = {
                "session_id": session_id,
                "subject_id": (row or {}).get("subject_id"),
                "patient_id": (row or {}).get("patient_id"),
                "start_timestamp_utc": (row or {}).get("start_timestamp_utc"),
                "total_frames": _try_get_parquet_row_count(parquet_path),
                "duration_sec": None,  # not recoverable after the fact — engine only ever held this in memory
                "backfilled": True,
            }
            result = session_uploader.upload(parquet_path, session_id, metadata, queue_on_failure=True)
            if result.get("ok"):
                summary["sessions_uploaded_now"] += 1
            else:
                # upload() already queued it into pending_uploads on failure —
                # the background scheduler takes over retrying from here.
                summary["sessions_queued_now"] += 1

        # --- Session log (best-effort, independent of the Parquet outcome above) ---
        if local_license_cache.is_session_log_synced(session_id) or session_id in already_pending_log_ids:
            continue
        log_file = log_files.get(session_id)
        if log_file and log_file.exists():
            log_result = session_uploader.upload_log(log_file, session_id, queue_on_failure=True)
            if log_result.get("ok"):
                summary["logs_uploaded_now"] += 1
            else:
                summary["logs_queued_now"] += 1

    if (summary["sessions_uploaded_now"] or summary["sessions_queued_now"]
            or summary["logs_uploaded_now"] or summary["logs_queued_now"]):
        logger.info(f"Historical session backfill sweep: {summary}")
    return summary
