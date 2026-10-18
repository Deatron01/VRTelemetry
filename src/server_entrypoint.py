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

from pathlib import Path

import uvicorn

from src.config import get_settings, reset_settings_cache
from src.interfaces.api.app import create_app
from src.license_service.local_cache import LocalLicenseCache
from src.storage.hub_address import is_configured
from src.storage.local_hub_kit import adopt_local_hub_kit
from src.utils.logger import logger, setup_logging


def _adopt_local_hub_kit() -> None:
    """Point an unconfigured workstation at a hub installed on this machine.

    Runs before anything else reads settings, and drops the cached copy if it
    changed ``config.toml``, so the whole process sees one configuration. The
    working directory is where :func:`get_settings` reads ``config.toml``
    from, and the desktop app sets it to the data root.
    """
    settings = get_settings()
    if is_configured(settings.central.url):
        return
    saved = LocalLicenseCache(settings.paths.license_cache_db).get_config("central_server_url")
    if adopt_local_hub_kit(Path.cwd(), settings.central, saved_url=saved):
        reset_settings_cache()


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
    _adopt_local_hub_kit()
    api = get_settings().api
    logger.info(f"Bootstrapping VRTelemetry backend server on {api.host}:{api.port}...")

    uvicorn.run(create_app(), host=api.host, port=api.port, log_level="info")


if __name__ == "__main__":
    boot_server_context()
