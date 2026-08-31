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

from src.interfaces.api.app import create_app
from src.utils.logger import logger, setup_logging


def boot_server_context() -> None:
    """Boot the FastAPI server the Electron-hosted frontend talks to.

    As opposed to ``src/interfaces/cli/record.py``, which drives the same
    acquisition pipeline directly from the command line with no HTTP involved.

    Binds to loopback deliberately: the workstation API is the desktop app's
    own backend, not a LAN service. Making that address configurable, and
    reconciling it with the CORS allow-list, is VRT-16.
    """
    setup_logging()
    logger.info("Bootstrapping VRTelemetry backend server for desktop shell...")

    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    boot_server_context()
