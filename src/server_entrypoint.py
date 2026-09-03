# src/server_entrypoint.py
"""Desktop-app entry point: the process the Electron shell spawns.

This is what ``build/backend.spec`` freezes and what ``electron/`` starts in a
packaged install, so it is the one module whose import behaviour a *user* pays
for rather than a developer.

It used to read ``from src.main import app`` at module scope. Every import of
this module -- including the one PyInstaller performs while analysing the
frozen bundle -- therefore built the whole application: three SQLite databases
opened, two uploaders constructed, the licence cache read. The application is
now built inside :func:`boot_server_context`, where it belongs: the only caller
that wants an application is the one about to serve requests with it.
"""

from __future__ import annotations

import uvicorn

from src.config import get_settings
from src.interfaces.api.app import create_app
from src.utils.logger import logger, setup_logging


def boot_server_context() -> None:
    """Boot the FastAPI server the Electron-hosted frontend talks to.

    As opposed to ``src/interfaces/cli/record.py``, which drives the same
    acquisition pipeline directly from the command line with no HTTP involved.

    Binds to loopback **by default and on purpose**: this API serves patient
    records and starts recordings, and only the desktop app on this machine
    should reach it. The hub is the thing other machines talk to.

    The address comes from :class:`~src.config.settings.ApiSettings` rather than
    from two literals here. It was hardcoded to ``127.0.0.1:8000`` while
    ``VRT_API__HOST`` / ``VRT_API__PORT`` existed, were documented in
    ``config.example.toml``, were validated for port collisions against the hub,
    and did nothing -- so an installation that moved the port got a desktop
    shell talking to a backend that was not there.
    """
    setup_logging()
    api = get_settings().api
    logger.info(f"Bootstrapping VRTelemetry backend server on {api.host}:{api.port}...")

    uvicorn.run(create_app(), host=api.host, port=api.port, log_level="info")


if __name__ == "__main__":
    boot_server_context()
