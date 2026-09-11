# src/interfaces/api/dependencies.py
"""How a request handler gets hold of a collaborator (VRT-12).

Every name here resolves out of the :class:`~src.interfaces.api.container.Container`
that :func:`~src.interfaces.api.app.create_app` stored on ``app.state``. Nothing
in this module is constructed at import; there are no module-level objects at
all. That is the whole point of the ticket.

What it used to be
------------------

Eleven module-level singletons. VRT-10 moved them here from ``src/main.py``,
which stopped construction being interleaved with route definitions but changed
nothing about *when* it happened: importing this module still opened three
SQLite databases, built two HTTP uploaders and read the licence cache. The
consequences were concrete rather than theoretical:

* A CLI run paid for the API's databases and never used them.
* Changing the central server address through ``POST /api/config/central-server``
  did not repoint the live uploaders, because they had captured the URL at
  import. It took an app restart. That is fixed here -- the uploaders are built
  from the same resolver the config route writes to, and a container is built
  per application rather than per process.
* A test could not substitute a fake. It could only ``monkeypatch.setattr`` a
  module attribute and hope every caller reached for it by the same path --
  and one of them did not, which is how VRT-10 shipped a fixture that patched
  ``src.main.http_requests`` while the routers went on using the real library.

Why ``Annotated`` aliases
-------------------------

Each provider gets a type alias (``SessionsDep``, ``PatientsDep``, ...) so a
handler's signature reads ``sessions: SessionsDep`` rather than repeating
``Depends(...)`` at 29 call sites. The aliases are also the override keys: a
test replaces one collaborator with
``app.dependency_overrides[dependencies.get_sessions] = lambda: fake``, scoped
to that test rather than to the process.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from src.application.consent import ConsentService
from src.config import Settings
from src.infrastructure.persistence import SessionRepository
from src.interfaces.api.container import Container, RecordingSessionManager
from src.license_service.local_cache import LocalLicenseCache
from src.patients.patient_manager import PatientManager
from src.storage.database_manager import DatabaseManager
from src.storage.heartbeat_client import HeartbeatSender
from src.storage.patient_sync_client import PatientSyncClient
from src.storage.session_uploader import SessionUploader
from src.storage.sync_scheduler import BackgroundSyncScheduler
from src.storage.usage_tracker import UsageTracker

__all__ = [
    "CentralUrlDep",
    "ConsentsDep",
    "ContainerDep",
    "DbManagerDep",
    "HeartbeatDep",
    "HttpDep",
    "LocalCacheDep",
    "PatientUploaderDep",
    "PatientsDep",
    "RecordingDep",
    "SessionUploaderDep",
    "SessionsDep",
    "SettingsDep",
    "SyncSchedulerDep",
    "UsageTrackerDep",
    "get_container",
]


def get_container(request: Request) -> Container:
    """The container this request's application was built with.

    Args:
        request: The live request; FastAPI supplies it.

    Returns:
        The application's container.

    Raises:
        RuntimeError: when the application was not built by
            :func:`~src.interfaces.api.app.create_app`. Failing loudly here
            beats an ``AttributeError`` surfacing as a 500 from whichever route
            happened to be hit first.
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError(
            "No container on app.state. The application must be built by "
            "create_app(), which is what wires it."
        )
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


# --------------------------------------------------------------------------- #
# One provider per collaborator.
#
# Written out rather than generated from a list of attribute names: a generated
# provider has no return annotation for mypy to check and no stable identity for
# `dependency_overrides` to key on. Thirteen three-line functions is the cheaper
# side of that trade.
# --------------------------------------------------------------------------- #


def get_settings_for_request(container: ContainerDep) -> Settings:
    """Configuration this application was built against."""
    return container.settings


def get_sessions(container: ContainerDep) -> SessionRepository:
    """Reads and writes of ``session_metadata``."""
    return container.sessions


def get_patients(container: ContainerDep) -> PatientManager:
    """The patient registry and its consent lifecycle."""
    return container.patients


def get_consents(container: ContainerDep) -> ConsentService:
    """The participant consent register (GDPR-09)."""
    return container.consents


def get_local_cache(container: ContainerDep) -> LocalLicenseCache:
    """Licence state, the auth session and the local key/value config."""
    return container.local_cache


def get_session_uploader(container: ContainerDep) -> SessionUploader:
    """Pushes recorded sessions and their logs to the hub."""
    return container.session_uploader


def get_patient_uploader(container: ContainerDep) -> PatientSyncClient:
    """Pushes patient records to the hub."""
    return container.patient_uploader


def get_usage_tracker(container: ContainerDep) -> UsageTracker:
    """Local usage events, for the licence audit trail."""
    return container.usage_tracker


def get_db_manager(container: ContainerDep) -> DatabaseManager:
    """Retained for ``persist_experiment`` and the backfill sweep (VRT-14)."""
    return container.db_manager


def get_sync_scheduler(container: ContainerDep) -> BackgroundSyncScheduler:
    """The periodic upload sweep."""
    return container.sync_scheduler


def get_heartbeat_sender(container: ContainerDep) -> HeartbeatSender:
    """The loop that tells the hub this workstation is alive."""
    return container.heartbeat_sender


def get_recording(container: ContainerDep) -> RecordingSessionManager:
    """The one recording this application may have in flight."""
    return container.recording


def get_http(container: ContainerDep) -> Any:
    """The HTTP client for outbound calls to the hub.

    Typed ``Any`` deliberately: the production value is the ``requests`` module
    and the test value is a stub exposing the four verbs plus
    ``RequestException``. Neither is an instance of a shared protocol yet;
    declaring one is VRT-14, where the outbound calls move behind a port.
    """
    return container.http


def get_central_url(container: ContainerDep) -> str:
    """The hub address, resolved per request.

    Per request, not once at startup: ``POST /api/config/central-server`` writes
    the address into the local cache, and the next call here picks it up. The
    old module-level ``central_url()`` captured it at import, so changing the
    address did nothing until the app was restarted.
    """
    return container.central_url()


SettingsDep = Annotated[Settings, Depends(get_settings_for_request)]
SessionsDep = Annotated[SessionRepository, Depends(get_sessions)]
PatientsDep = Annotated[PatientManager, Depends(get_patients)]
ConsentsDep = Annotated[ConsentService, Depends(get_consents)]
LocalCacheDep = Annotated[LocalLicenseCache, Depends(get_local_cache)]
SessionUploaderDep = Annotated[SessionUploader, Depends(get_session_uploader)]
PatientUploaderDep = Annotated[PatientSyncClient, Depends(get_patient_uploader)]
UsageTrackerDep = Annotated[UsageTracker, Depends(get_usage_tracker)]
DbManagerDep = Annotated[DatabaseManager, Depends(get_db_manager)]
SyncSchedulerDep = Annotated[BackgroundSyncScheduler, Depends(get_sync_scheduler)]
HeartbeatDep = Annotated[HeartbeatSender, Depends(get_heartbeat_sender)]
RecordingDep = Annotated[RecordingSessionManager, Depends(get_recording)]
HttpDep = Annotated[Any, Depends(get_http)]
CentralUrlDep = Annotated[str, Depends(get_central_url)]
