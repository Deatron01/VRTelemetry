# src/interfaces/api/app.py
"""The workstation API application factory (VRT-10).

``src/main.py`` built its FastAPI app at module scope, so importing the module
created the app, opened three databases and registered 29 routes as a side
effect. One process could hold exactly one app, which is why the API had no
tests: there was no way to construct a second one against a temporary data root.

:func:`create_app` replaces that. It is still a thin factory -- the
collaborators it wires in are the same module-level singletons, now collected in
``dependencies.py`` -- but the app itself is built on demand, and the routers it
mounts know nothing about how those collaborators came to exist. That is the
seam VRT-12 needs.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.interfaces.api import dependencies as deps
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


def create_app() -> FastAPI:
    """Build the workstation API.

    Returns:
        A FastAPI application with all 29 routes mounted and the startup and
        shutdown handlers registered.
    """
    app = FastAPI(title="VRTelemetry Unified Backend")

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        # Was allow_origins=["*"] with allow_credentials=True -- a combination
        # browsers reject outright, so it was simultaneously over-permissive in
        # intent and non-functional in practice. Now configured, and narrowed
        # properly in VRT-16.
        allow_origins=list(settings.api.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in _ROUTERS:
        app.include_router(router)

    _register_lifecycle(app)
    return app


def _register_lifecycle(app: FastAPI) -> None:
    """Attach the boot sweep and the background loops.

    Still ``@app.on_event``, which FastAPI deprecates in favour of a lifespan
    context manager. Converting it is a behaviour change around startup and
    shutdown ordering, and belongs with VRT-12 where the loops themselves stop
    being module-level singletons -- not inside a commit whose entire claim is
    that nothing behaves differently.
    """
    from src.interfaces.api.routers.licence import repair_missing_license_id
    from src.interfaces.api.routers.sync import run_session_backfill

    @app.on_event("startup")
    def _start_background_sync_and_heartbeat() -> None:
        # Immediate sweep on boot, then hand off to the periodic scheduler and
        # heartbeat loop for the rest of the process's lifetime.
        try:
            repair_missing_license_id()
        except Exception as exc:
            logger.warning(f"license_id repair on boot failed: {exc}")
        try:
            run_session_backfill()
        except Exception as exc:
            logger.warning(f"Session backfill sweep on boot failed: {exc}")
        try:
            deps.sync_scheduler.sweep_once()
        except Exception as exc:
            logger.warning(f"Initial sync sweep on boot failed: {exc}")
        deps.sync_scheduler.start()
        deps.heartbeat_sender.start()

    @app.on_event("shutdown")
    def _stop_background_sync_and_heartbeat() -> None:
        deps.sync_scheduler.stop()
        deps.heartbeat_sender.stop()
