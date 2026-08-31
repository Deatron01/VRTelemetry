# src/interfaces/api/app.py
"""The workstation API application factory (VRT-10, completed by VRT-12).

``src/main.py`` built its FastAPI app at module scope, so importing the module
created the app, opened three databases and registered 29 routes as a side
effect. One process could hold exactly one app, which is why the API had no
tests: there was no way to construct a second one against a temporary data root.

:func:`create_app` is now a real factory. It builds a
:class:`~src.interfaces.api.container.Container` -- or accepts one -- stores it
on ``app.state``, and mounts routers that reach their collaborators through
``Depends``. Two applications can exist in one process against separate data
roots, and neither knows anything about the other.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.interfaces.api.container import Container, build_container
from src.interfaces.api.routers import (
    auth,
    config,
    licence,
    patients,
    questionnaires,
    recording,
    sessions,
    sync,
)
from src.utils.logger import logger

#: Mounted in this order. Ordering is not arbitrary: FastAPI matches routes in
#: registration order, and `/api/sessions/{session_id}` would otherwise shadow
#: `/api/sessions/{session_id}/telemetry` depending on how the two are declared.
#: The sessions router keeps its internal order from before the split for
#: exactly that reason.
_ROUTERS = (
    sessions.router,
    questionnaires.router,
    recording.router,
    patients.router,
    auth.router,
    licence.router,
    sync.router,
    config.router,
)


def create_app(container: Container | None = None) -> FastAPI:
    """Build the workstation API.

    Args:
        container: The collaborators to serve requests from. Defaults to a
            container built from process configuration, which is what
            production wants. A test passes its own, pointed at a temporary
            data root and holding whatever fakes it needs -- which is the
            entire reason this parameter exists.

    Returns:
        A FastAPI application with all 29 routes mounted and its lifespan
        registered. Nothing has started yet: the background loops start when
        the application does, not when it is constructed, so building one in a
        test spawns no threads and reaches no network.
    """
    container = container or build_container()

    app = FastAPI(title="VRTelemetry Unified Backend", lifespan=_lifespan)
    # Every provider in dependencies.py resolves from here. Set before the
    # routers are mounted so there is no window in which a route exists and its
    # collaborators do not.
    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        # Was allow_origins=["*"] with allow_credentials=True -- a combination
        # browsers reject outright, so it was simultaneously over-permissive in
        # intent and non-functional in practice. Now configured, and narrowed
        # properly in VRT-16.
        allow_origins=list(container.settings.api.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in _ROUTERS:
        app.include_router(router)

    return app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the boot sweep and the background loops; stop them on shutdown.

    Replaces the pair of ``@app.on_event`` handlers, which FastAPI deprecates
    and which had a defect the deprecation is unrelated to: they closed over
    module-level singletons, so the loops they started belonged to the process
    rather than to the application. Two apps in one process fought over one
    scheduler. Here everything comes from ``app.state.container``, so an app
    starts and stops exactly its own.

    Every boot step is individually guarded. A workstation whose hub is
    unreachable -- the normal state for a researcher on a laptop away from the
    lab -- must still come up and serve the local UI.
    """
    container = app.state.container

    # Imported here rather than at module scope: both modules import the
    # routers package, and this module is what the routers package is mounted
    # from. The cycle is real, and this is the seam that breaks it.
    from src.interfaces.api.routers.licence import repair_missing_license_id
    from src.interfaces.api.routers.sync import run_session_backfill

    for label, step in (
        ("license_id repair", lambda: repair_missing_license_id(container)),
        ("session backfill sweep", lambda: run_session_backfill(container)),
        ("initial sync sweep", container.sync_scheduler.sweep_once),
    ):
        try:
            step()
        except Exception as exc:
            logger.warning(f"{label} on boot failed: {exc}")

    container.sync_scheduler.start()
    container.heartbeat_sender.start()
    try:
        yield
    finally:
        container.sync_scheduler.stop()
        container.heartbeat_sender.stop()
