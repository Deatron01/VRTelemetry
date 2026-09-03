# src/storage/patient_sync_client.py

import json
import logging
from collections.abc import Callable
from typing import Any

from src.application.ports import HttpClient
from src.storage.hub_address import (
    HUB_NOT_CONFIGURED,
    HUB_NOT_CONFIGURED_MESSAGE,
    is_configured,
)
from src.utils.retry_backoff import is_ready_for_retry

logger = logging.getLogger(__name__)


class PatientSyncClient:
    """
    Pushes every patient-record mutation (create, edit, consent withdrawal,
    erasure) to the central hub immediately — this is not a manual/optional
    sync path. If the central server is unreachable the mutation is queued
    locally and retried automatically (on next app boot and via the same
    /api/sync/retry sweep the session uploader uses).

    Central keeps its own permanent copy of every patient it has ever
    received, per license, mirroring how AsyncParquetWriter/SessionUploader
    already treat recorded sessions as centrally authoritative.
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

        #: Required, with no default -- see SessionUploader for why (VRT-14).
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

    def _active_state(self):
        state = self.local_license_cache.get_state()
        if not state or state.get("status") != "active":
            return None
        return state

    def sync_patient(
        self, patient: dict[str, Any], queue_on_failure: bool = True
    ) -> dict[str, Any]:
        state = self._active_state()

        if "patient_id" not in patient:
            if "subject_id" in patient:
                patient["patient_id"] = patient["subject_id"]
            else:
                logger.error("Cannot sync patient: Missing patient_id")
                return {"ok": False, "reason": "malformed_patient_data"}

        if not state:
            logger.warning("Skipping patient sync — no active license cached locally.")
            if queue_on_failure:
                self._queue(patient)
            return {"ok": False, "reason": "no_active_license"}

        # Before the request, not inside the except: an empty address makes the
        # URL relative, and requests raises MissingSchema -- a RequestException,
        # so it used to be reported as an unreachable server. See
        # src/storage/hub_address.py.
        if not is_configured(self.central_server_url):
            logger.warning(f"Patient sync deferred — {HUB_NOT_CONFIGURED_MESSAGE}.")
            if queue_on_failure:
                self._queue(patient)
            return {"ok": False, "reason": HUB_NOT_CONFIGURED}

        try:
            response = self.http.post(
                f"{self.central_server_url}/data/upload-patient",
                json={
                    "activation_id": state["activation_id"],
                    "license_id": state.get("license_id") or "",
                    "patient": patient,
                },
                timeout=30,
            )
            if response.status_code == 200:
                self.local_license_cache.clear_pending_patient_sync(patient["patient_id"])
                return response.json()
            logger.error(f"Patient sync rejected ({response.status_code}): {response.text}")
            if queue_on_failure:
                self._queue(patient)
                self.local_license_cache.record_patient_sync_failure(
                    patient["patient_id"], response.text
                )
            return {"ok": False, "reason": response.text}
        except self.http.RequestException as e:
            logger.warning(f"Patient sync failed, queued for retry: {e}")
            if queue_on_failure:
                self._queue(patient)
                self.local_license_cache.record_patient_sync_failure(patient["patient_id"], str(e))
            return {"ok": False, "reason": "network_error", "detail": str(e)}

    def retry_pending(self) -> dict[str, Any]:
        pending = self.local_license_cache.list_pending_patient_syncs()
        due = [item for item in pending if is_ready_for_retry(item)]
        if not due:
            return {"attempted": 0, "succeeded": 0}
        succeeded = 0
        for item in due:
            patient = json.loads(item["payload_json"])
            if self.sync_patient(patient, queue_on_failure=True).get("ok"):
                succeeded += 1
        logger.info(
            f"Pending patient sync retry: {succeeded}/{len(due)} succeeded ({len(pending)} total pending)."
        )
        return {"attempted": len(due), "succeeded": succeeded}

    def _queue(self, patient: dict[str, Any]) -> None:
        self.local_license_cache.queue_pending_patient_sync(
            patient["patient_id"], json.dumps(patient)
        )
