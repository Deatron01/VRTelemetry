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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.application.consent import ConsentService
from src.application.erasure import ErasureService
from src.application.ports import HttpClient
from src.config import Settings, get_settings
from src.core.biosensor_status import BiosensorStatusRegistry
from src.infrastructure.persistence import SessionRepository
from src.infrastructure.persistence.av_recording_repository import AVRecordingRepository
from src.infrastructure.persistence.biosensor_repository import BiosensorStreamRepository
from src.infrastructure.persistence.consent_repository import ConsentRepository
from src.infrastructure.transport import default_http_client
from src.interfaces.api.event_router import EventRouter
from src.license_service.local_cache import LocalLicenseCache
from src.patients.consent_texts import build_catalogue
from src.patients.patient_manager import PatientManager
from src.plugin_manager import PluginManager
from src.storage.database_manager import DatabaseManager
from src.storage.heartbeat_client import HeartbeatSender
from src.storage.patient_sync_client import PatientSyncClient
from src.storage.session_uploader import SessionUploader
from src.storage.sync_scheduler import BackgroundSyncScheduler
from src.storage.usage_tracker import UsageTracker
from src.utils.logger import logger

if TYPE_CHECKING:
    from src.av_recording.session_recorder import SessionRecorder
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
        #: The A/V ``SessionRecorder`` running alongside the current engine, if
        #: any (A/V recording is off by default, and even on, only runs when
        #: the participant's consent includes P-C7 -- see
        #: ``src.interfaces.api.routers.recording``). Held under the same lock
        #: and cleared together with the engine so the two can never disagree
        #: about whether a recording is in flight.
        self._av_recorder: SessionRecorder | None = None

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

    @property
    def av_recorder(self) -> SessionRecorder | None:
        """The A/V recorder for the current session, or None. A snapshot."""
        with self._lock:
            return self._av_recorder

    def attach_av_recorder(self, recorder: SessionRecorder) -> None:
        """Associate an already-started A/V recorder with the current session.

        Called by the recording route right after ``TelemetryEngine`` is
        published, never before -- A/V capture is additive to a telemetry
        session, not a precondition for one.
        """
        with self._lock:
            self._av_recorder = recorder

    def pop_av_recorder(self) -> SessionRecorder | None:
        """Take and clear the current A/V recorder, for :meth:`stop`'s caller to finish.

        Popped rather than read-and-cleared separately so a second concurrent
        stop request cannot both act on the same recorder.
        """
        with self._lock:
            recorder, self._av_recorder = self._av_recorder, None
            return recorder

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
        # Released before calling into the engine: the teardown that follows
        # seals the writer and joins the consumer thread, and holding a lock
        # across that would block every status read for its duration.
        #
        # Called unconditionally. This used to be `if hasattr(engine, "stop")`
        # with `engine.is_running = False` as the fallback, and a comment saying
        # the fallback never ran because the engine always had `stop()`. It
        # never did -- the fallback was the only path -- so the manager was
        # reaching into the engine and setting a flag, which happened to be
        # exactly what stopping means and was therefore never noticed.
        # TelemetryEngine.stop() exists as of VRT-14 and says so itself.
        engine.stop()
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
    #: The consent register and its rules (GDPR-09). Shares ``patients.db``
    #: with the patient registry, so a participant and the evidence of their
    #: consent live in one file.
    consents: ConsentService
    #: Right to erasure across workstation files, metadata and the hub (GDPR-10).
    erasure: ErasureService
    #: A/V recording metadata (P-C7): one row per session that had one
    #: attempted. Never touched by anything in the hub-upload path -- see
    #: ``src.infrastructure.persistence.av_recording_repository``.
    av_recordings: AVRecordingRepository
    local_cache: LocalLicenseCache
    session_uploader: SessionUploader
    patient_uploader: PatientSyncClient
    usage_tracker: UsageTracker
    db_manager: DatabaseManager
    sync_scheduler: BackgroundSyncScheduler
    heartbeat_sender: HeartbeatSender
    recording: RecordingSessionManager
    #: The plugin bus (VR Telemetry Hub plugin architecture). See the naming
    #: note at the top of ``src/interfaces/api/event_router.py`` -- distinct
    #: from ``HubSettings``/``central_server`` above, which is a different hub.
    event_router: EventRouter
    plugin_manager: PluginManager
    #: Per-session, per-device provenance for biosensor plugin streams
    #: (VRT-34) -- which device sent what, how much, when. Sample values
    #: themselves live in each session's sidecar Parquet, never here; see
    #: src/storage/biosensor_sidecar.py.
    biosensor_streams: BiosensorStreamRepository
    #: Latest status heartbeat from each connected biosensor producer
    #: (VRT-36), independent of whether a recording is running -- see that
    #: class's docstring for why it lives here rather than on the engine.
    biosensor_status: BiosensorStatusRegistry

    #: The HTTP client every outbound call goes through. An attribute rather
    #: than a direct import so a test replaces one object instead of patching a
    #: name in eight router modules.
    #:
    #: No default (VRT-14). It used to default to the ``requests`` module, which
    #: read as "production is the normal case" and was true of the routers only:
    #: the three clients below held their own reference, so replacing this field
    #: repointed the routers and left the uploaders on the network. Requiring it
    #: means the wiring happens in exactly one place, and :meth:`__post_init__`
    #: refuses a container where it happened in only some of them.
    http: HttpClient

    def __post_init__(self) -> None:
        """Refuse a container whose collaborators disagree about the network.

        ``dataclasses.replace(container, http=stub)`` is the obvious way to
        build an offline container, and before VRT-14 it half-worked: the field
        changed, the routers followed it, and ``SessionUploader``,
        ``PatientSyncClient`` and ``HeartbeatSender`` carried on using the real
        library. A test written that way passes while reaching the network, and
        an unreachable server looks identical to a working stub from the
        assertion's side. This is the same class of defect as the false-green
        fixture VRT-12 removed, so it is made impossible rather than documented.

        Raises:
            ValueError: if any client holds a different client to this field.
        """
        mismatched = [
            name
            for name, client in (
                ("session_uploader", self.session_uploader),
                ("patient_uploader", self.patient_uploader),
                ("heartbeat_sender", self.heartbeat_sender),
            )
            if getattr(client, "http", self.http) is not self.http
        ]
        if mismatched:
            raise ValueError(
                f"Container.http is not the client held by {', '.join(mismatched)}. "
                f"Every outbound call must go through one object, or an 'offline' "
                f"container reaches the network through the ones that were missed. "
                f"Build it with build_container(settings, http=...) rather than "
                f"replacing the field afterwards."
            )

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


def build_container(settings: Settings | None = None, http: HttpClient | None = None) -> Container:
    """Construct every collaborator for one application instance.

    This is the only place in the codebase that calls these constructors. If
    something needs building, it is built here and injected; nothing reaches out
    to fetch a collaborator from a module namespace.

    Args:
        settings: Configuration to build against. Defaults to the process
            settings, which is what production wants; tests pass their own
            pointed at a temporary data root.
        http: The outbound HTTP client, handed to the routers *and* to the three
            clients that make their own calls. Defaults to the real one. A test
            that wants to stay offline passes its stub here -- not by replacing
            the field afterwards, which :meth:`Container.__post_init__` refuses.

    Returns:
        A fully wired container. Nothing is started -- the background loops are
        started by the application's lifespan, so constructing a container in a
        test spawns no threads.
    """
    settings = settings or get_settings()
    settings.ensure_directories()
    # The production client is held to the TLS policy (GDPR-01). A test that
    # passes its own stub gets exactly that stub: the policy has its own tests
    # in tests/unit/test_transport.py.
    http = http if http is not None else default_http_client(settings.central)

    local_cache = LocalLicenseCache(settings.paths.license_cache_db)
    recording = RecordingSessionManager()

    # VR Telemetry Hub plugin architecture (VRT-26..31). Constructing these
    # starts no threads and opens no sockets -- EventRouter.bind_loop() and
    # PluginManager.start_all() are called from the app's lifespan, not here,
    # so building a container in a test still spawns nothing.
    event_router = EventRouter(
        shared_token=settings.plugin_bus.shared_token,
        max_queue_per_client=settings.plugin_bus.max_queue_per_client,
    )
    plugin_manager = PluginManager(
        registry_path=settings.paths.data_root / settings.plugin_bus.registry_path,
        plugins_dir=settings.paths.data_root / settings.plugin_bus.plugins_checkout_dir,
        venvs_dir=settings.paths.data_root / settings.plugin_bus.plugins_venv_dir,
        logs_dir=settings.paths.data_root / settings.paths.logs_dir_name / "plugins",
        hub_ws_url=settings.plugin_bus.hub_ws_url,
        hub_plugin_token=settings.plugin_bus.shared_token,
    )

    def _resolve_central_url() -> str:
        configured = settings.central.url or ""
        return local_cache.get_config("central_server_url", configured) or configured

    # The resolver, not its current value: an address changed through
    # POST /api/config/central-server takes effect on the next upload rather
    # than on the next app restart.
    session_uploader = SessionUploader(_resolve_central_url, local_cache, http=http)
    patient_uploader = PatientSyncClient(_resolve_central_url, local_cache, http=http)

    def _status() -> str:
        return "recording" if recording.is_running else "idle"

    def _pending() -> int:
        try:
            return (
                len(local_cache.list_pending_uploads())
                + len(local_cache.list_pending_session_logs())
                + len(local_cache.list_pending_patient_syncs())
                + len(local_cache.list_pending_erasures())
            )
        except Exception as exc:  # noqa: BLE001 - a status probe must never raise
            logger.debug(f"Pending count unavailable: {exc}")
            return 0

    sessions = SessionRepository(settings.paths.metadata_db)
    patients = PatientManager(settings.paths.patients_db)
    av_recordings = AVRecordingRepository(settings.paths.metadata_db)
    consents = ConsentService(
        ConsentRepository(settings.paths.patients_db),
        # Built on each call rather than once: cheap, and it keeps the
        # wording in step with the settings object this container holds.
        catalogue_provider=lambda: build_catalogue(settings.consent),
    )

    def _is_recording_patient(patient_id: str) -> bool:
        engine = recording.engine
        if not recording.is_running or engine is None:
            return False
        static = engine.subject_metadata.get("M-IV_Static_Metadata", {})
        return bool(static.get("patient_id") == patient_id)

    biosensor_streams = BiosensorStreamRepository(settings.paths.metadata_db)
    biosensor_status = BiosensorStatusRegistry(
        stale_after_sec=settings.biosensor.status_stale_after_sec
    )

    container = Container(
        settings=settings,
        sessions=sessions,
        patients=patients,
        consents=consents,
        av_recordings=av_recordings,
        erasure=ErasureService(
            patients=patients,
            sessions=sessions,
            consents=consents,
            queues=local_cache,
            hub=patient_uploader,
            sessions_dir=settings.paths.sessions_dir,
            session_logs_dir=settings.paths.session_logs_dir,
            is_recording_patient=_is_recording_patient,
            av_recordings=av_recordings,
            biosensor_streams=biosensor_streams,
        ),
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
            http=http,
            interval_sec=settings.sync.heartbeat_interval_sec,
            status_provider=_status,
            pending_count_provider=_pending,
        ),
        recording=recording,
        event_router=event_router,
        plugin_manager=plugin_manager,
        biosensor_streams=biosensor_streams,
        biosensor_status=biosensor_status,
        http=http,
    )
    logger.debug(f"Container built against data root {settings.paths.data_root}")
    return container
