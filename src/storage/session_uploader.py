# src/storage/session_uploader.py

import json
import logging
import requests
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SessionUploader:
    """
    Pushes a completed recording session to the central hub server.
    On any failure, the session is queued in LocalLicenseCache.pending_uploads
    so it isn't lost — retry_pending() sweeps that queue on next engine start
    or on-demand from the UI.
    """

    def __init__(self, central_server_url: str, local_license_cache):
        self.central_server_url = central_server_url.rstrip("/")
        self.local_license_cache = local_license_cache

    def upload(self, parquet_path: Path, session_id: str, metadata: Dict[str, Any],
               queue_on_failure: bool = True) -> Dict[str, Any]:
        state = self.local_license_cache.get_state()
        if not state or state.get("status") != "active":
            logger.warning("Skipping upload — no active license cached locally.")
            if queue_on_failure:
                self._queue(session_id, parquet_path, metadata)
            return {"ok": False, "reason": "no_active_license"}

        if not parquet_path.exists():
            logger.error(f"Cannot upload — file not found: {parquet_path}")
            return {"ok": False, "reason": "file_not_found"}

        try:
            with open(parquet_path, "rb") as f:
                response = requests.post(
                    f"{self.central_server_url}/data/upload-session",
                    data={
                        "activation_id": state["activation_id"],
                        "license_id": state.get("license_id", ""),
                        "machine_label": state.get("machine_label", ""),
                        "session_id": session_id,
                        "metadata_json": json.dumps(metadata),
                    },
                    files={"file": (parquet_path.name, f, "application/octet-stream")},
                    timeout=120,
                )
            if response.status_code == 200:
                logger.info(f"Session {session_id} uploaded to central server.")
                self.local_license_cache.clear_pending_upload(session_id)
                return response.json()
            else:
                logger.error(f"Upload rejected ({response.status_code}): {response.text}")
                if queue_on_failure:
                    self._queue(session_id, parquet_path, metadata)
                    self.local_license_cache.record_upload_attempt_failure(session_id, response.text)
                return {"ok": False, "reason": response.text}
        except requests.RequestException as e:
            logger.warning(f"Upload failed, queued for retry: {e}")
            if queue_on_failure:
                self._queue(session_id, parquet_path, metadata)
                self.local_license_cache.record_upload_attempt_failure(session_id, str(e))
            return {"ok": False, "reason": "network_error", "detail": str(e)}

    def retry_pending(self) -> Dict[str, Any]:
        """
        Sweeps the local pending-upload queue. Called on engine start and
        exposed via a manual 'Sync Now' action in the UI.
        """
        pending = self.local_license_cache.list_pending_uploads()
        if not pending:
            return {"attempted": 0, "succeeded": 0}

        succeeded = 0
        for item in pending:
            path = Path(item["parquet_path"])
            metadata = json.loads(item["metadata_json"])
            result = self.upload(path, item["session_id"], metadata, queue_on_failure=True)
            if result.get("ok"):
                succeeded += 1

        logger.info(f"Pending upload retry: {succeeded}/{len(pending)} succeeded.")
        return {"attempted": len(pending), "succeeded": succeeded}

    def _queue(self, session_id: str, parquet_path: Path, metadata: Dict[str, Any]) -> None:
        self.local_license_cache.queue_pending_upload(
            session_id, str(parquet_path), json.dumps(metadata)
        )
        
    def upload_log(self, log_path: Path, session_id: str) -> Dict[str, Any]:
        state = self.local_license_cache.get_state()
        if not state or state.get("status") != "active":
            return {"ok": False, "reason": "no_active_license"}
        if not log_path.exists():
            return {"ok": False, "reason": "log_file_not_found"}

        try:
            with open(log_path, "rb") as f:
                response = requests.post(
                    f"{self.central_server_url}/data/upload-session-log",
                    data={
                        "activation_id": state["activation_id"],
                        "license_id": state.get("license_id", ""),
                        "session_id": session_id,
                    },
                    files={"file": (log_path.name, f, "text/plain")},
                    timeout=60,
                )
            if response.status_code == 200:
                return response.json()
            return {"ok": False, "reason": response.text}
        except requests.RequestException as e:
            return {"ok": False, "reason": "network_error", "detail": str(e)}