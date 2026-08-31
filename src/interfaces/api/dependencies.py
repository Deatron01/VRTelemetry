# src/interfaces/api/dependencies.py
"""The collaborators every router shares (VRT-10).

These objects used to be eleven module-level singletons scattered through
``src/main.py``, constructed at import time between route definitions -- so
importing the module opened three SQLite databases, built an HTTP uploader and
read the licence cache before a single request had arrived.

Collecting them here changes nothing about *when* they are built; it only
stops that construction being interleaved with the API surface. The inversion
-- FastAPI ``Depends`` resolving from a container built in ``create_app()``,
with nothing constructed at import -- is VRT-12. Until then this module is one
honest place to look for the seam rather than eleven scattered ones.

Two things are deliberately reachable as *module attributes* rather than
imported into each router's namespace:

``http_requests``
    The alias every outbound call goes through. Routers call
    ``dependencies.http_requests.post(...)``, never a name bound at import, so
    a test can substitute an unreachable-server stub in one place and have it
    apply everywhere.

``recording_state``
    Mutable session state. It replaces the ``global active_engine`` /
    ``global engine_thread`` pair, which could not survive the routers being
    split across modules -- ``global`` is module-scoped, and four different
    routers need to see the same engine.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import requests as http_requests

from src.config import get_settings
from src.core.engine import TelemetryEngine
from src.infrastructure.persistence import SessionRepository
from src.license_service.local_cache import LocalLicenseCache
from src.patients.patient_manager import PatientManager
from src.storage.database_manager import DatabaseManager
from src.storage.heartbeat_client import HeartbeatSender
from src.storage.patient_sync_client import PatientSyncClient
from src.storage.session_uploader import SessionUploader
from src.storage.sync_scheduler import BackgroundSyncScheduler
from src.storage.usage_tracker import UsageTracker

__all__ = [
    "central_url",
    "db_manager",
    "db_path",
    "dict_factory",
    "heartbeat_sender",
    "http_requests",
    "local_cache",
    "patient_uploader",
    "patients",
    "recording_state",
    "session_uploader",
    "sessions",
    "sessions_log_dir",
    "sessions_output_dir",
    "sync_scheduler",
    "usage_tracker",
]


# --------------------------------------------------------------------------- #
# Recording session state
# --------------------------------------------------------------------------- #


@dataclass
class RecordingState:
    """The one recording this process may have in flight.

    Replaces two module-level globals. There is deliberately no locking here
    yet: the previous code had none either, and adding it is a behaviour change
    that belongs with the RecordingSessionManager in VRT-12, where the
    threading contract can be stated and tested rather than assumed.
    """

    engine: TelemetryEngine | None = None
    thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """True when an engine exists and reports itself as recording."""
        return bool(self.engine and getattr(self.engine, "is_running", False))


recording_state = RecordingState()


# --------------------------------------------------------------------------- #
# Paths and the hub address
# --------------------------------------------------------------------------- #


def db_path() -> str:
    """Where the session metadata database lives, per configuration.

    Resolved on each call rather than bound once, so it follows the configured
    data root instead of whichever directory the process started in (VRT-6).
    """
    return str(get_settings().paths.metadata_db)


def central_url() -> str:
    """The hub address: the researcher's own setting first, then configuration.

    Returns an empty string when neither is set. Callers treat that the same
    way they treat an unreachable server -- work locally and queue -- which is
    a supported state, unlike the placeholder address this used to fall back to.
    """
    configured = get_settings().central.url or ""
    return local_cache.get_config("central_server_url", configured)


def dict_factory(cursor, row):
    """Row factory returning dicts, so routes can serialise rows directly."""
    return {col[0]: row[index] for index, col in enumerate(cursor.description)}


# --------------------------------------------------------------------------- #
# The singletons
# --------------------------------------------------------------------------- #

usage_tracker = UsageTracker()
local_cache = LocalLicenseCache()
patients = PatientManager()

#: Shared DatabaseManager (vr_metadata.db) for the API and the historical
#: backfill sweep alike -- the metadata rows for every session recorded locally
#: live here, independent of whether a sync attempt was ever made for them.
db_manager = DatabaseManager()

#: Every read and write of session_metadata goes through here. DatabaseManager
#: above is retained only for persist_experiment, which the engine calls while
#: recording; folding that in is VRT-14, where the engine stops constructing its
#: own collaborators.
sessions = SessionRepository()

#: Persistent uploaders, used by the background sync scheduler and the manual
#: "Sync Now" endpoint alike, so both paths share one retry/backoff history
#: instead of the ad-hoc per-request instances the old code constructed.
session_uploader = SessionUploader(central_url(), local_cache)
patient_uploader = PatientSyncClient(central_url(), local_cache)

#: The same roots TelemetryEngine and the CLI resolve from settings -- this is
#: where session_uploader.upload() expects to find vr_telemetry_<id>.parquet
#: and where attach_session_log_capture() writes session_<id>.log.
sessions_output_dir = str(get_settings().paths.sessions_dir)
sessions_log_dir = str(get_settings().paths.session_logs_dir)


def current_client_status() -> str:
    """What the heartbeat reports this machine is doing right now."""
    return "recording" if recording_state.is_running else "idle"


def current_pending_count() -> int:
    """How much this machine still has queued for upload."""
    try:
        return (
            len(local_cache.list_pending_uploads())
            + len(local_cache.list_pending_session_logs())
            + len(local_cache.list_pending_patient_syncs())
        )
    except Exception:
        return 0


#: Sweeps pending sessions, logs and patients on a timer for as long as this
#: backend process is alive -- that is, for as long as the desktop app is open
#: -- regardless of whether a recording is active or anyone is watching the UI.
sync_scheduler = BackgroundSyncScheduler(
    session_uploader, patient_uploader, interval_sec=get_settings().sync.interval_sec
)

#: Pings the hub with this machine's activation_id and machine_label so the
#: admin "Active Clients" tab can show live online/offline status, along with
#: current engine state and outstanding sync backlog.
heartbeat_sender = HeartbeatSender(
    central_server_url_provider=central_url,
    local_license_cache=local_cache,
    interval_sec=get_settings().sync.heartbeat_interval_sec,
    status_provider=current_client_status,
    pending_count_provider=current_pending_count,
)
