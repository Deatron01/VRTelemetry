# src/storage/session_uploader.py

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.application.ports import HttpClient
from src.storage.hub_address import (
    HUB_NOT_CONFIGURED,
    HUB_NOT_CONFIGURED_MESSAGE,
    is_configured,
)
from src.utils.retry_backoff import is_ready_for_retry

logger = logging.getLogger(__name__)


class SessionUploader:
    """
    Pushes a completed recording session to the central hub server.
    On any failure, the session is queued in LocalLicenseCache.pending_uploads
    so it isn't lost — retry_pending() sweeps that queue on next engine start
    or on-demand from the UI.
    """

    def __init__(
        self,
        central_server_url: str | Callable[[], str],
        local_license_cache,
        http: HttpClient,
    ):
        # Accepts a callable so the address stays late-bound: POST
        # /api/config/central-server writes a new hub address into the local
        # cache, and before VRT-12 this object had already captured the old one
        # at construction, so every upload kept going to the previous server
        # until the app was restarted -- with nothing anywhere saying so.
        self._central_server_url = central_server_url
        self.local_license_cache = local_license_cache

        #: Required, with no default (VRT-14). A default of `requests` would be
        #: used the first time a caller forgot to pass one, and the test that
        #: was supposed to be offline would reach the network instead --
        #: indistinguishable, from the assertion's side, from a stub that
        #: raises. `build_container` is the only place that supplies the real
        #: one; see src/infrastructure/transport.py.
        self.http = http

    @property
    def central_server_url(self) -> str:
        """The hub address, resolved on each read and without a trailing slash.

        Empty when the hub is unconfigured. That is a supported state: uploads
        queue locally rather than being attempted against a placeholder.
        """
        value = self._central_server_url
        if callable(value):
            value = value()
        return (value or "").rstrip("/")

    @central_server_url.setter
    def central_server_url(self, value: str | Callable[[], str]) -> None:
        self._central_server_url = value

    def upload(
        self,
        parquet_path: Path,
        session_id: str,
        metadata: dict[str, Any],
        queue_on_failure: bool = True,
    ) -> dict[str, Any]:
        state = self.local_license_cache.get_state()
        if not state or state.get("status") != "active":
            logger.warning("Skipping upload — no active license cached locally.")
            if queue_on_failure:
                self._queue(session_id, parquet_path, metadata)
            return {"ok": False, "reason": "no_active_license"}

        if not parquet_path.exists():
            logger.warning(
                f"Pending upload for session {session_id} references a file that no longer exists "
                f"({parquet_path}) — this data is permanently unrecoverable. Removing from the retry "
                f"queue instead of retrying forever."
            )
            self.local_license_cache.clear_pending_upload(session_id)
            return {"ok": False, "reason": "file_not_found_removed_from_queue"}

        # Before the request, not inside the except: an empty address makes the
        # URL relative, and requests raises MissingSchema -- a RequestException,
        # so it used to be reported as an unreachable server. See
        # src/storage/hub_address.py.
        if not is_configured(self.central_server_url):
            logger.warning(f"Session {session_id} kept locally — {HUB_NOT_CONFIGURED_MESSAGE}.")
            if queue_on_failure:
                self._queue(session_id, parquet_path, metadata)
            return {"ok": False, "reason": HUB_NOT_CONFIGURED}

        try:
            with open(parquet_path, "rb") as f:
                response = self.http.post(
                    f"{self.central_server_url}/data/upload-session",
                    data={
                        "activation_id": state["activation_id"],
                        "license_id": state.get("license_id") or "",
                        "machine_label": state.get("machine_label", ""),
                        "session_id": session_id,
                        "metadata_json": json.dumps(metadata),
                    },
                    files={"file": (parquet_path.name, f, "application/octet-stream")},
                    timeout=120,
                )
            if response.status_code == 200:
                data = response.json()
                if data.get("verified") is False:
                    # The central server itself detected a post-write checksum mismatch.
                    # Treating a 200 as success here would silently discard the researcher's
                    # only remaining copy of a file the server admits is corrupt.
                    logger.error(
                        f"Central server flagged session {session_id} as CORRUPT "
                        f"(post-write checksum mismatch). Keeping local copy queued for retry."
                    )
                    if queue_on_failure:
                        self._queue(session_id, parquet_path, metadata)
                        self.local_license_cache.record_upload_attempt_failure(
                            session_id, "server_reported_checksum_mismatch"
                        )
                    return {
                        "ok": False,
                        "reason": "server_verification_failed",
                        "upload_id": data.get("upload_id"),
                    }

                logger.info(f"Session {session_id} uploaded to central server.")
                self.local_license_cache.clear_pending_upload(session_id)
                # Confirmed-synced ledger — lets the historical backfill sweep skip this
                # session on future scans instead of re-sending an already-accepted file.
                self.local_license_cache.mark_session_synced(session_id, data.get("upload_id", ""))
                return data
            else:
                logger.error(f"Upload rejected ({response.status_code}): {response.text}")
                if queue_on_failure:
                    self._queue(session_id, parquet_path, metadata)
                    self.local_license_cache.record_upload_attempt_failure(
                        session_id, response.text
                    )
                return {"ok": False, "reason": response.text}
        except self.http.RequestException as e:
            logger.warning(f"Upload failed, queued for retry: {e}")
            if queue_on_failure:
                self._queue(session_id, parquet_path, metadata)
                self.local_license_cache.record_upload_attempt_failure(session_id, str(e))
            return {"ok": False, "reason": "network_error", "detail": str(e)}

    def update_remote_metadata(self, session_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Best-effort metadata-only re-sync, used right after a post-session
        questionnaire is saved locally. Deliberately NOT queued/retried like
        upload()/upload_log() — the local session_metadata row is always the
        source of truth for this data, so a failed re-sync here just means
        the central copy is stale until the next full sync touches it (e.g.
        a future backfill pass or an admin re-pull); it never loses data.
        """
        state = self.local_license_cache.get_state()
        if not state or state.get("status") != "active":
            return {"ok": False, "reason": "no_active_license"}
        if not is_configured(self.central_server_url):
            # Not queued, deliberately: this method never queues. The local row
            # is the source of truth, so there is nothing to lose here.
            logger.debug(f"Metadata re-sync for session {session_id} skipped — no hub configured.")
            return {"ok": False, "reason": HUB_NOT_CONFIGURED}
        try:
            response = self.http.post(
                f"{self.central_server_url}/data/update-session-metadata",
                data={
                    "activation_id": state["activation_id"],
                    "license_id": state.get("license_id") or "",
                    "session_id": session_id,
                    "metadata_json": json.dumps(metadata),
                },
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
            logger.info(
                f"Metadata re-sync for session {session_id} did not update the central copy "
                f"({response.status_code}): {response.text}. Local record is unaffected."
            )
            return {"ok": False, "reason": response.text}
        except self.http.RequestException as e:
            logger.info(
                f"Metadata re-sync for session {session_id} skipped — central server unreachable: {e}"
            )
            return {"ok": False, "reason": "network_error", "detail": str(e)}

    def retry_pending(self) -> dict[str, Any]:
        """
        Sweeps the local pending-upload queue. Called on engine start, by the
        BackgroundSyncScheduler on its periodic tick, and exposed via a manual
        'Sync Now' action in the UI. Items that failed recently are skipped
        this pass (see is_ready_for_retry) so a persistently-unreachable server
        doesn't get hammered every tick — they'll be picked up once their
        backoff window elapses.
        """
        pending = self.local_license_cache.list_pending_uploads()
        due = [item for item in pending if is_ready_for_retry(item)]
        if not due:
            return {"attempted": 0, "succeeded": 0}

        succeeded = 0
        for item in due:
            path = Path(item["parquet_path"])
            metadata = json.loads(item["metadata_json"])
            result = self.upload(path, item["session_id"], metadata, queue_on_failure=True)
            if result.get("ok"):
                succeeded += 1

        logger.info(
            f"Pending upload retry: {succeeded}/{len(due)} succeeded ({len(pending)} total pending)."
        )
        return {"attempted": len(due), "succeeded": succeeded}

    def _queue(self, session_id: str, parquet_path: Path, metadata: dict[str, Any]) -> None:
        self.local_license_cache.queue_pending_upload(
            session_id, str(parquet_path), json.dumps(metadata)
        )

    def upload_log(
        self, log_path: Path, session_id: str, queue_on_failure: bool = True
    ) -> dict[str, Any]:
        state = self.local_license_cache.get_state()
        if not state or state.get("status") != "active":
            if queue_on_failure and log_path.exists():
                self._queue_log(session_id, log_path)
            return {"ok": False, "reason": "no_active_license"}
        if not log_path.exists():
            logger.warning(
                f"Pending log upload for session {session_id} references a file that no longer "
                f"exists ({log_path}) — removing from the retry queue instead of retrying forever."
            )
            self.local_license_cache.clear_pending_session_log(session_id)
            return {"ok": False, "reason": "file_not_found_removed_from_queue"}

        if not is_configured(self.central_server_url):
            logger.warning(
                f"Session log for {session_id} kept locally — {HUB_NOT_CONFIGURED_MESSAGE}."
            )
            if queue_on_failure:
                self._queue_log(session_id, log_path)
            return {"ok": False, "reason": HUB_NOT_CONFIGURED}

        try:
            with open(log_path, "rb") as f:
                response = self.http.post(
                    f"{self.central_server_url}/data/upload-session-log",
                    data={
                        "activation_id": state["activation_id"],
                        "license_id": state.get("license_id") or "",
                        "session_id": session_id,
                    },
                    files={"file": (log_path.name, f, "text/plain")},
                    timeout=60,
                )
            if response.status_code == 200:
                self.local_license_cache.clear_pending_session_log(session_id)
                self.local_license_cache.mark_session_log_synced(session_id)
                return response.json()
            logger.warning(
                f"Log upload rejected for session {session_id} ({response.status_code}): {response.text}"
            )
            if queue_on_failure:
                self._queue_log(session_id, log_path)
                self.local_license_cache.record_session_log_attempt_failure(
                    session_id, response.text
                )
            return {"ok": False, "reason": response.text}
        except self.http.RequestException as e:
            logger.warning(f"Log upload failed for session {session_id}, queued for retry: {e}")
            if queue_on_failure:
                self._queue_log(session_id, log_path)
                self.local_license_cache.record_session_log_attempt_failure(session_id, str(e))
            return {"ok": False, "reason": "network_error", "detail": str(e)}

    def retry_pending_logs(self) -> dict[str, Any]:
        """Sweeps the local pending-session-log queue, same shape as retry_pending()."""
        pending = self.local_license_cache.list_pending_session_logs()
        due = [item for item in pending if is_ready_for_retry(item)]
        if not due:
            return {"attempted": 0, "succeeded": 0}

        succeeded = 0
        for item in due:
            result = self.upload_log(
                Path(item["log_path"]), item["session_id"], queue_on_failure=True
            )
            if result.get("ok"):
                succeeded += 1

        logger.info(
            f"Pending log retry: {succeeded}/{len(due)} succeeded ({len(pending)} total pending)."
        )
        return {"attempted": len(due), "succeeded": succeeded}

    def _queue_log(self, session_id: str, log_path: Path) -> None:
        self.local_license_cache.queue_pending_session_log(session_id, str(log_path))
