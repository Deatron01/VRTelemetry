# src/storage/sync_scheduler.py

import threading
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class BackgroundSyncScheduler:
    """
    Owns the periodic "sweep everything that failed to sync and try again"
    loop for sessions (Parquet files), session logs, and patient records.

    Before this existed, retrying a failed sync only happened when the
    telemetry engine started a new recording (TelemetryEngine.start calls
    uploader.retry_pending() once) or when a researcher manually hit the
    'Sync Now' button — so data queued while the app was simply sitting idle
    (or while a patient was edited with no recording running) could sit
    unsynced indefinitely. This scheduler runs for the lifetime of the local
    backend process instead, independent of engine/UI state, which is what
    makes sync "automatic" rather than something that has to be triggered.
    """

    def __init__(self, session_uploader, patient_uploader, interval_sec: float = 20.0):
        self.session_uploader = session_uploader
        self.patient_uploader = patient_uploader
        self.interval_sec = interval_sec

        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()  # guards against an on-demand sweep overlapping the scheduled one

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="BackgroundSyncScheduler")
        self._thread.start()
        logger.info(f"Background sync scheduler started (interval={self.interval_sec}s).")

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.sweep_once()
            self._stop_event.wait(self.interval_sec)

    def sweep_once(self) -> Dict[str, Any]:
        """
        Runs one full sweep across all three pending queues. Safe to call
        directly (e.g. from a manual 'Sync Now' API call) as well as from the
        scheduled loop — a lock keeps the two from racing each other and
        double-uploading the same item.
        """
        result = {
            "sessions": {"attempted": 0, "succeeded": 0},
            "logs": {"attempted": 0, "succeeded": 0},
            "patients": {"attempted": 0, "succeeded": 0},
        }
        if not self._lock.acquire(blocking=False):
            logger.debug("Sync sweep already in progress, skipping this tick.")
            return result

        try:
            try:
                result["sessions"] = self.session_uploader.retry_pending()
            except Exception as e:
                logger.warning(f"Background session sync sweep failed: {e}")

            try:
                result["logs"] = self.session_uploader.retry_pending_logs()
            except Exception as e:
                logger.warning(f"Background log sync sweep failed: {e}")

            try:
                result["patients"] = self.patient_uploader.retry_pending()
            except Exception as e:
                logger.warning(f"Background patient sync sweep failed: {e}")
        finally:
            self._lock.release()

        total_attempted = sum(r.get("attempted", 0) for r in result.values())
        if total_attempted:
            logger.info(f"Background sync sweep: {result}")
        return result
