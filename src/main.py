# src/main.py
"""Backward-compatibility shim (VRT-10).

This file was 1,185 lines: the argparse CLI, the whole FastAPI surface, every
Pydantic schema, raw SQL against three databases, anthropometric domain maths,
licence repair logic, and eleven singletons constructed at import time between
route definitions. Imports appeared at lines 632, 784, 904 and 1027, including
``import hashlib`` twelve lines *after* its first use, annotated "add near top
imports".

It is now a shim. Everything lives where it belongs:

===========================================  ==================================
``src/interfaces/api/app.py``                ``create_app()``, CORS, lifecycle
``src/interfaces/api/routers/``              8 modules, 29 routes
``src/interfaces/api/schemas/``              request models, one per domain
``src/interfaces/api/dependencies.py``       the shared collaborators
``src/interfaces/cli/record.py``             the acquisition CLI
``src/domain/session_profile.py``            anthropometrics, health profile
``src/utils/metadata.py``                    ``sanitize_metadata``
===========================================  ==================================

The names below are re-exported because things outside this repository import
them: ``electron/backend-manager.js`` spawns ``uvicorn src.main:app`` in
development, ``build/backend.spec`` freezes an entry point that reaches it, and
the characterisation suite reaches ``src.main`` directly. Removing this shim is
a coordinated change across all three and is not part of VRT-10.

New code should import from the modules above, not from here.
"""

from __future__ import annotations

from src.interfaces.api import dependencies as _deps
from src.interfaces.api.app import create_app
from src.interfaces.cli.record import execute_pipeline, parse_arguments
from src.utils.metadata import sanitize_metadata

#: The application instance uvicorn and the Electron shell expect at
#: ``src.main:app``. Built once here, exactly as before -- ``create_app()`` is
#: what lets tests build their own against a temporary data root instead.
app = create_app()

__all__ = [
    "app",
    "create_app",
    "execute_pipeline",
    "parse_arguments",
    "sanitize_metadata",
]


def __getattr__(name: str) -> object:
    """Resolve the old private module-level names to their new home.

    ``src.main._patients``, ``_local_cache``, ``_session_uploader`` and the rest
    were never public, but the characterisation suite reaches for them to seed
    state, and doing that through a mapping here keeps those 63 tests pointed at
    one module while the implementation moves out from under them.

    Deliberately a mapping rather than plain assignments: an assignment would
    bind a *copy* of the reference at import, so a test patching
    ``src.main._local_cache`` would leave the routers using the original object
    and quietly prove nothing. Resolving on each access means the shim and the
    routers always see the same object.

    Args:
        name: The attribute being looked up.

    Returns:
        The collaborator from ``src.interfaces.api.dependencies``.

    Raises:
        AttributeError: for anything not in the compatibility map.
    """
    legacy = {
        "_patients": "patients",
        "_local_cache": "local_cache",
        "_session_uploader": "session_uploader",
        "_patient_uploader": "patient_uploader",
        "_db_manager_for_sync": "db_manager",
        "_usage": "usage_tracker",
        "_sync_scheduler": "sync_scheduler",
        "_heartbeat_sender": "heartbeat_sender",
        "_central_url": "central_url",
        "_db_path": "db_path",
        "http_requests": "http_requests",
    }
    if name in legacy:
        return getattr(_deps, legacy[name])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    execute_pipeline()
