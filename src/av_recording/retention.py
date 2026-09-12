# src/av_recording/retention.py
"""Delete each session's captured video once its transcript is verified.

Addendum Section 2.4: storage-limitation (Art. 5(1)(e) GDPR) is easiest to
satisfy by deleting the raw video once its transcript exists and has been
generated successfully, rather than keeping it "just in case" -- so that is
the default (``AVRecordingSettings.raw_recording_retention_days = 0``). The
transcript and any future derived score follow the study's own retention
period (``ConsentSettings.retention``), which this module does not enforce:
that is free-text describing a date or event, not a machine-checkable rule.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from src.infrastructure.persistence.av_recording_repository import AVRecordingRepository
from src.utils.clock import as_stored, utc_now, utc_now_iso
from src.utils.logger import logger


def sweep_av_retention(repository: AVRecordingRepository, *, retention_days: int) -> dict[str, int]:
    """Delete the video for every session past its retention window.

    Mirrors ``SessionUploader.retry_pending()``'s shape: safe to call whether
    or not anything is due, meant to run on engine start and on a periodic
    sweep. Only ever deletes the *video* file -- the transcript, and its
    ``av_recordings`` row, are untouched.

    Args:
        repository: Where A/V recording rows live.
        retention_days: ``AVRecordingSettings.raw_recording_retention_days``.
            0 means "due as soon as the transcript is verified" -- the cutoff
            is simply now.

    Returns:
        ``{"checked": n, "deleted": n}``.
    """
    cutoff = as_stored(utc_now() - timedelta(days=retention_days))
    due = repository.due_for_retention_sweep(cutoff)
    deleted = 0
    for row in due:
        video_path = Path(row["video_path"]) if row["video_path"] else None
        try:
            if video_path is not None and video_path.exists():
                video_path.unlink()
            repository.update(row["session_id"], {"raw_recording_deleted_at_utc": utc_now_iso()})
            deleted += 1
        except OSError as exc:
            logger.warning(
                f"Could not delete the A/V recording for session {row['session_id']} on the "
                f"retention sweep (will retry next sweep): {exc}"
            )
    if due:
        logger.info(f"A/V retention sweep: deleted {deleted}/{len(due)} due recording(s).")
    return {"checked": len(due), "deleted": deleted}
