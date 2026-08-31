# src/main.py
"""Backward-compatibility shim (VRT-10, narrowed by VRT-12).

This file was 1,185 lines: the argparse CLI, the whole FastAPI surface, every
Pydantic schema, raw SQL against three databases, anthropometric domain maths,
licence repair logic, and eleven singletons constructed at import time between
route definitions. Imports appeared at lines 632, 784, 904 and 1027, including
``import hashlib`` twelve lines *after* its first use, annotated "add near top
imports".

It is now a shim. Everything lives where it belongs:

===========================================  ==================================
``src/interfaces/api/app.py``                ``create_app()``, CORS, lifespan
``src/interfaces/api/container.py``          the composition root
``src/interfaces/api/routers/``              8 modules, 29 routes
``src/interfaces/api/schemas/``              request models, one per domain
``src/interfaces/api/dependencies.py``       the ``Depends`` providers
``src/interfaces/cli/record.py``             the acquisition CLI
``src/domain/session_profile.py``            anthropometrics, health profile
``src/utils/metadata.py``                    ``sanitize_metadata``
===========================================  ==================================

``app`` is still here because things outside this repository reach for it:
``electron/backend-manager.js`` spawns ``uvicorn src.main:app`` in development
and ``build/backend.spec`` freezes an entry point that resolves it. Removing the
shim is a coordinated change across both and is not part of VRT-12.

It is built **lazily**, on first attribute access, rather than assigned at
module scope. ``uvicorn src.main:app`` imports the module and then reads the
attribute, so that path is unaffected; but merely importing ``src.main`` -- as
the CLI does, and as any tooling that walks the package does -- no longer opens
three databases and reads the licence cache. There is a test asserting that no
module under ``src/`` performs I/O at import.

VRT-9's legacy private aliases (``_patients``, ``_local_cache``, ``_db_path``
and the rest) are **gone**. They existed so the characterisation suite could
reach the singletons while VRT-10 through VRT-12 moved them; the suite now
builds its own application from its own container, which is what it wanted all
along. Nothing else ever referenced them.

New code should import from the modules above, not from here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.interfaces.api.app import create_app
from src.interfaces.cli.record import execute_pipeline, parse_arguments
from src.utils.metadata import sanitize_metadata

if TYPE_CHECKING:  # pragma: no cover - for type checkers and readers only
    from fastapi import FastAPI

    app: FastAPI

__all__ = [
    "app",
    "create_app",
    "execute_pipeline",
    "parse_arguments",
    "sanitize_metadata",
]


def __getattr__(name: str) -> Any:
    """Build the ASGI application on first access to ``src.main.app``.

    PEP 562: this runs only when normal attribute lookup fails, and the result
    is cached into the module's globals, so the application is built exactly
    once no matter how many times ``app`` is read.

    Args:
        name: The attribute being looked up.

    Returns:
        The ASGI application, for ``name == "app"``.

    Raises:
        AttributeError: for anything else, including every legacy private alias
            this module used to resolve.
    """
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    execute_pipeline()
