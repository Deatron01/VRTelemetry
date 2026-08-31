# src/interfaces/api/container.py
"""The composition root: where every collaborator is built, once (VRT-12).

This is the ticket the previous four were clearing the way for.

``src/main.py`` used to construct eleven objects at module scope, interleaved
with route definitions. Importing it opened three SQLite databases, built two
HTTP uploaders and read the licence cache -- before any request existed, and
whether or not the process intended to serve one. A CLI run paid for the API. A
test could not substitute a fake, because by the time the test ran, the real
thing was already built and bound. That is why the API had zero coverage for its
entire life.

VRT-10 collected those objects into one module; they were still built at import.
This builds them here, on demand, from configuration passed in -- so:

* **importing any module performs no I/O.** There is a test that imports every
  module in ``src/`` with ``sqlite3.connect``, ``open`` and ``socket.socket``
  patched to raise, and asserts nothing tries.
* **two applications can coexist** in one process against separate data roots,
  which is what lets the characterisation suite build a real app per test
  instead of monkeypatching module attributes and hoping.
* **a fake is injected, not patched.** ``app.dependency_overrides`` replaces a
  provider; nothing has to reach into another module's namespace.

The container is deliberately a plain frozen dataclass rather than a DI
framework. The graph is a dozen objects wide and one deep. A framework would
add a registration DSL, lifetime scopes and a resolution order to reason about,
in exchange for nothing this shape of problem needs.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import requests

from src.config import Settings, get_settings
from src.infrastructure.persistence import SessionRepository
from src.license_service.local_cache import LocalLicenseCache
from src.patients.patient_manager import PatientManager
from src.storage.database_manager import DatabaseManager
from src.storage.heartbeat_client import HeartbeatSender
from src.storage.patient_sync_client import PatientSyncClient
from src.storage.session_uploader import SessionUploader
from src.storage.sync_scheduler import BackgroundSyncScheduler
from src.storage.usage_tracker import UsageTracker
from src.utils.logger import logger

if TYPE_CHECKING:
    from src.core.engine import TelemetryEngine


class RecordingSessionManager:
    """The one recording a process may have in flight, with a stated contract.

    Replaces ``global active_engine`` / ``global engine_thread``. Those were
    read from request threads and written from a route handler with no
    synchronisation at all -- a data race that happened not to bite because a
    researcher clicks Start once. "Happens not to bite" is not a contract.

    The contract, stated because it was previously only implied:

    * At most one recording at a time. :meth:`start` refuses a second.
    * ``engine`` and ``thread`` are only ever mutated while holding ``_lock``.
    * :meth:`is_running` is a snapshot. A caller acting on it must tolerate the
      recording having stopped in between -- which is why :meth:`stop` re-checks
      under the lock rather than trusting what the caller saw.
    * The engine thread is a daemon: a researcher closing the app must not be
      blocked by an acquisition loop that is mid-frame.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engine: TelemetryEngine | None = None
        self._thread: threading.Thread | None = None

    @property
    def engine(self) -> TelemetryEngine | None:
        """The active engine, or None. A snapshot; may be stale on return."""
        with self._lock:
            return self._engine

    @property
    def is_running(self) -> bool:
        """Whether a recording is in flight right now."""
        with self._lock:
            return bool(self._engine and getattr(self._engine, "is_running", False))

    def start(self, engine: TelemetryEngine, target: Any) -> threading.Thread:
        """Adopt ``engine`` and run ``target`` against it on a daemon thread.

        The engine is published *before* the thread starts: the four live-state
        routes and the heartbeat's status provider can be hit the instant the
        caller's handler returns.

        Args:
            engine: The engine to take ownership of.
            target: Callable invoked with the engine on the new thread.

        Returns:
            The started thread.

        Raises:
            RuntimeError: if a recording is already in flight. The caller turns
                this into the 400 the API has always returned.
        """
        with self._lock:
            if self._engine and getattr(self._engine, "is_running", False):
                raise RuntimeError("A telemetry session is already running.")
            self._engine = engine
            thread = threading.Thread(target=target, args=(engine,), daemon=True)
            self._thread = thread
        thread.start()
        return thread

    def stop(self) -> bool:
        """Signal the active recording to stop.

        Returns:
            True if a recording was stopped, False if there was nothing to stop.
        """
        with self._lock:
            engine = self._engine
            if not (engine and getattr(engine, "is_running", False)):
                return False
        # Released before calling into the engine: stop() joins threads and
        # flushes the writer, and holding a lock across that would block every
        # status read for the duration of a teardown.
        if hasattr(engine, "stop"):
            engine.stop()
        else:
            engine.is_running = False
        return True


@dataclass(frozen=True)
class Container:
    """Everything the API needs, built once per application.

    Frozen: a request handler may read these, never rebind them. Swapping one
    out is ``app.dependency_overrides``, which is scoped to a test rather than
    to the process.
    """

    settings: Settings
    sessions: SessionRepository
    patients: PatientManager
    local_cache: LocalLicenseCache
    session_uploader: SessionUploader
    patient_uploader: PatientSyncClient
    usage_tracker: UsageTracker
    db_manager: DatabaseManager
    sync_scheduler: BackgroundSyncScheduler
    heartbeat_sender: HeartbeatSender
    recording: RecordingSessionManager

    #: The HTTP client every outbound call goes through. An attribute rather
    #: than a direct import so a test replaces one object instead of patching a
    #: name in eight router modules.
    http: Any = field(default=requests)

    @property
    def sessions_output_dir(self) -> str:
        """Where session_uploader expects vr_telemetry_<id>.parquet."""
        return str(self.settings.paths.sessions_dir)

    @property
    def sessions_log_dir(self) -> str:
        """Where attach_session_log_capture writes session_<id>.log."""
        return str(self.settings.paths.session_logs_dir)

    def central_url(self) -> str:
        """The hub address: the researcher's own setting first, then configuration.

        Empty when neither is set. Callers treat that exactly as they treat an
        unreachable server -- work locally and queue -- which is supported,
        unlike the placeholder address this used to fall back to.
        """
        configured = self.settings.central.url or ""
        return self.local_cache.get_config("central_server_url", configured) or configured


def build_container(settings: Settings | None = None) -> Container:
    """Construct every collaborator for one application instance.

    This is the only place in the codebase that calls these constructors. If
    something needs building, it is built here and injected; nothing reaches out
    to fetch a collaborator from a module namespace.

    Args:
        settings: Configuration to build against. Defaults to the process
            settings, which is what production wants; tests pass their own
            pointed at a temporary data root.

    Returns:
        A fully wired container. Nothing is started -- the background loops are
        started by the application's lifespan, so constructing a container in a
        test spawns no threads.
    """
    settings = settings or get_settings()
    settings.ensure_directories()

    local_cache = LocalLicenseCache(settings.paths.license_cache_db)
    recording = RecordingSessionManager()

    def _resolve_central_url() -> str:
        configured = settings.central.url or ""
        return local_cache.get_config("central_server_url", configured) or configured

    # The resolver, not its current value: an address changed through
    # POST /api/config/central-server takes effect on the next upload rather
    # than on the next app restart.
    session_uploader = SessionUploader(_resolve_central_url, local_cache)
    patient_uploader = PatientSyncClient(_resolve_central_url, local_cache)

    def _status() -> str:
        return "recording" if recording.is_running else "idle"

    def _pending() -> int:
        try:
            return (
                len(local_cache.list_pending_uploads())
                + len(local_cache.list_pending_session_logs())
                + len(local_cache.list_pending_patient_syncs())
            )
        except Exception as exc:  # noqa: BLE001 - a status probe must never raise
            logger.debug(f"Pending count unavailable: {exc}")
            return 0

    container = Container(
        settings=settings,
        sessions=SessionRepository(settings.paths.metadata_db),
        patients=PatientManager(settings.paths.patients_db),
        local_cache=local_cache,
        session_uploader=session_uploader,
        patient_uploader=patient_uploader,
        usage_tracker=UsageTracker(settings.paths.usage_db),
        db_manager=DatabaseManager(settings.paths.metadata_db),
        sync_scheduler=BackgroundSyncScheduler(
            session_uploader, patient_uploader, interval_sec=settings.sync.interval_sec
        ),
        heartbeat_sender=HeartbeatSender(
            central_server_url_provider=_resolve_central_url,
            local_license_cache=local_cache,
            interval_sec=settings.sync.heartbeat_interval_sec,
            status_provider=_status,
            pending_count_provider=_pending,
        ),
        recording=recording,
    )
    logger.debug(f"Container built against data root {settings.paths.data_root}")
    return container
