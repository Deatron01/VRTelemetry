# src/application/recording_context.py
"""What a recording needs, built in one place (VRT-14).

The composition root for acquisition, and the counterpart to
``src/interfaces/api/container.py``. VRT-12 did this for the API and left the
engine alone: ``TelemetryEngine.__init__`` still opened a database, started a
licence cache, constructed an HTTP uploader and allocated a Parquet writer, so
constructing one in a test meant three files on disk and a network client, and
"record a hundred frames and check they arrive" was not a thing that could be
written.

The shape is the same as the container's and for the same reasons:

* a frozen dataclass of collaborators, not a DI framework -- the graph is four
  objects wide and one deep;
* one function that builds the production set, which is the only place those
  constructors are called for a recording;
* everything else takes what it is given.

The one structural difference is that some of this is *session-scoped*. The
Parquet writer's path contains the session id, so these cannot be built once
per process the way the API's collaborators are; they are built per recording,
which is what :func:`build_recording_dependencies` takes its arguments for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.application.ports import (
    FrameSink,
    HardwareMetricsSource,
    SessionMetadataSink,
    SessionUploadPort,
)


@dataclass(frozen=True)
class RecordingDependencies:
    """The four collaborators a :class:`~src.core.engine.TelemetryEngine` needs.

    Frozen because a recording does not swap its sink halfway through. A test
    builds one from fakes; production gets one from
    :func:`build_recording_dependencies`.

    The synchroniser is deliberately absent. It is not a collaborator the engine
    reaches out to -- it is pure logic over the sink and the metrics source,
    with no I/O of its own, so it belongs to the engine rather than to its
    environment. Injecting it would make the engine's own behaviour
    substitutable, which is the opposite of what a port is for.
    """

    writer: FrameSink
    hardware: HardwareMetricsSource
    metadata_sink: SessionMetadataSink
    uploader: SessionUploadPort


def build_recording_dependencies(
    parquet_path: Path,
    *,
    central_server_url: str | None = None,
    target_hz: int = 120,
) -> RecordingDependencies:
    """Construct the production collaborators for one recording session.

    Every import here is local to the function. That is not style: importing
    this module must stay free of side effects (see
    ``tests/unit/test_no_import_time_io.py``), and these four constructors open
    SQLite databases and allocate an Arrow schema. The application layer is also
    not allowed to depend on ``src.infrastructure`` or ``src.storage`` at module
    scope -- dependencies point inward -- and a function-local import is how a
    composition root reaches outward without the layer doing so.

    Args:
        parquet_path: Where this session's frames are written. Session-scoped,
            which is why this function exists per recording rather than once.
        central_server_url: Hub address. ``None`` falls back to configuration,
            and an empty result is a supported state: uploads queue locally
            instead of being attempted against a placeholder.
        target_hz: Passed to the writer for its buffer sizing.

    Returns:
        Production dependencies. Nothing is started -- ``start()`` on the
        writer and the hardware monitor is the engine's to call, so building
        these in a test spawns no threads and opens no file handles beyond the
        databases.
    """
    from src.config import get_settings
    from src.infrastructure.transport import default_http_client
    from src.license_service.local_cache import LocalLicenseCache
    from src.storage.database_manager import DatabaseManager
    from src.storage.parquet_writer import AsyncParquetWriter
    from src.storage.session_uploader import SessionUploader
    from src.utils.hardware_monitor import HardwareMonitor

    settings = get_settings()
    local_license_cache = LocalLicenseCache()

    return RecordingDependencies(
        writer=AsyncParquetWriter(output_path=parquet_path, target_hz=target_hz),
        hardware=HardwareMonitor(),
        metadata_sink=DatabaseManager(),
        uploader=SessionUploader(
            central_server_url or settings.central.url or "",
            local_license_cache,
            http=default_http_client(),
        ),
    )
