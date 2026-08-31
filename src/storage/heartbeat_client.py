# src/storage/heartbeat_client.py

import logging
import platform
import threading
from collections.abc import Callable

import requests

logger = logging.getLogger(__name__)


class HeartbeatSender:
    """
    Runs for the lifetime of the local backend process — independent of
    whether a recording session is active — and pings the central server's
    /client/heartbeat every `interval_sec` seconds with this machine's
    activation_id and machine_label. This is what lets the Admin dashboard's
    "Active Clients" tab show accurate Online/Offline status instead of only
    knowing a machine exists once it happens to upload something.

    Deliberately has no retry queue of its own: a heartbeat that failed to
    arrive is not worth resending late (only "are you alive *now*" matters),
    so a failed ping is just logged and the next scheduled tick tries again —
    that's the retry.
    """

    def __init__(
        self,
        central_server_url_provider: Callable[[], str],
        local_license_cache,
        interval_sec: float = 30.0,
        status_provider: Callable[[], str] | None = None,
        pending_count_provider: Callable[[], int] | None = None,
        app_version: str = "1.0.0",
    ):
        self._url_provider = central_server_url_provider
        self.local_license_cache = local_license_cache
        self.interval_sec = interval_sec
        self._status_provider = status_provider or (lambda: "idle")
        self._pending_count_provider = pending_count_provider or (lambda: 0)
        self.app_version = app_version

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Whether the background loop is alive.

        Public because ``GET /api/sync/status`` reports it, and a route that
        reads ``._thread.is_alive()`` couples the admin UI to this class's
        private attributes (VRT-12).
        """
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="HeartbeatSender")
        self._thread.start()
        logger.info(f"Heartbeat sender started (interval={self.interval_sec}s).")

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.send_once()
            except Exception as e:
                # Defensive: this thread must never die, or the client silently
                # stops reporting as "online" for the rest of the process lifetime.
                logger.warning(f"Heartbeat tick raised unexpectedly: {e}")
            self._stop_event.wait(self.interval_sec)

    def send_once(self) -> bool:
        """Sends a single heartbeat ping now. Returns True on a 200 response."""
        state = self.local_license_cache.get_state()
        if not state or state.get("status") != "active" or not state.get("activation_id"):
            return False  # nothing activated on this machine yet — nothing to report

        try:
            response = requests.post(
                f"{self._url_provider().rstrip('/')}/client/heartbeat",
                data={
                    "activation_id": state["activation_id"],
                    "license_id": state.get("license_id") or "",
                    "machine_label": state.get("machine_label") or platform.node(),
                    "app_version": self.app_version,
                    "os_platform": platform.system(),
                    "status": self._status_provider(),
                    "pending_sync_count": self._pending_count_provider(),
                },
                timeout=10,
            )
            if response.status_code != 200:
                logger.debug(f"Heartbeat ping rejected ({response.status_code}): {response.text}")
                return False
            return True
        except requests.RequestException as e:
            logger.debug(f"Heartbeat ping failed, will retry in {self.interval_sec}s: {e}")
            return False
