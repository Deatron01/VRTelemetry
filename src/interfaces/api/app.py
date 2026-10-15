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

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.interfaces.api.container import Container, build_container
from src.interfaces.api.routers import (
    auth,
    biosensors,
    config,
    consent,
    licence,
    monitor,
    patients,
    plugins,
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
    consent.router,
    auth.router,
    licence.router,
    sync.router,
    config.router,
    plugins.router,
    monitor.router,
    biosensors.router,
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
        # intent and non-functional in practice. VRT-6 made it configurable;
        # VRT-16 narrowed the rest of it.
        allow_origins=list(container.settings.api.allowed_origins),
        # False, because nothing sends any. There is not a single
        # `credentials:` option in the frontend and this API sets no cookies --
        # auth state lives in the licence cache, server-side. Asking for
        # credentialed CORS you do not use buys nothing and costs the ability
        # to reason about who can call this.
        allow_credentials=False,
        allow_methods=list(container.settings.api.allowed_methods),
        allow_headers=list(container.settings.api.allowed_headers),
    )

    for router in _ROUTERS:
        app.include_router(router)

    # The Event Router's own APIRouter (/ws/hub/telemetry), mounted
    # separately from _ROUTERS above: it belongs to the plugin bus rather
    # than to the workstation's own REST surface, and it is built per-
    # container (it holds live WebSocket connections) rather than imported
    # as a module-level singleton like the routers in that tuple.
    app.include_router(container.event_router.router)

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

    loop = asyncio.get_running_loop()

    def _suppress_winerror_10054(loop, context):
        exc = context.get("exception")
        if (
            exc
            and isinstance(exc, ConnectionResetError)
            and getattr(exc, "winerror", None) == 10054
        ):
            return  # Suppress known noisy browser disconnects (VRT-24)
        loop.default_exception_handler(context)

    loop.set_exception_handler(_suppress_winerror_10054)

    # Imported here rather than at module scope: both modules import the
    # routers package, and this module is what the routers package is mounted
    # from. The cycle is real, and this is the seam that breaks it.
    from src.av_recording.retention import sweep_av_retention
    from src.interfaces.api.routers.licence import repair_missing_license_id
    from src.interfaces.api.routers.sync import run_session_backfill

    for label, step in (
        ("license_id repair", lambda: repair_missing_license_id(container)),
        ("session backfill sweep", lambda: run_session_backfill(container)),
        ("initial sync sweep", container.sync_scheduler.sweep_once),
        # A/V recording is off by default and this sweep touches only its own
        # table and its own video files (never session_metadata, never the
        # hub -- see av_recording_repository.py), so it is safe to run
        # unconditionally rather than gated on `consent.enable_av_recording`:
        # a workstation that has never recorded any A/V has nothing for it
        # to find due.
        (
            "A/V recording retention sweep",
            lambda: sweep_av_retention(
                container.av_recordings,
                retention_days=container.settings.av_recording.raw_recording_retention_days,
            ),
        ),
    ):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - boot step: the app must come up without a hub
            # The tolerant half of the rule this ticket encodes (see
            # src/core/exceptions.py). These steps talk to the hub, to the
            # local databases, and to the local A/V recording store; a
            # researcher on a laptop away from the lab has the first two
            # unreachable, and the local UI must still start. Each is
            # independently guarded so one failing does not cost the others.
            #
            # What makes this safe rather than lazy: none of the steps is a write
            # path. They are sweeps that retry from durable queues on the next
            # tick, so a failure here delays work rather than losing it.
            logger.warning(f"{label} on boot failed: {exc}", exc_info=True)

    # Bound before start_all(): a plugin's subprocess can connect to
    # /ws/hub/telemetry within moments of being spawned, and
    # publish_*_threadsafe must have a loop to hand work to by then (it logs
    # and drops rather than raising if this were skipped -- see
    # EventRouter.bind_loop's docstring -- but that would silently mean "no
    # plugin ever receives anything" for the life of the app).
    container.event_router.bind_loop(asyncio.get_running_loop())
    container.plugin_manager.start_all()

    container.sync_scheduler.start()
    container.heartbeat_sender.start()
    try:
        yield
    finally:
        container.sync_scheduler.stop()
        container.heartbeat_sender.stop()
        container.plugin_manager.stop_all()
