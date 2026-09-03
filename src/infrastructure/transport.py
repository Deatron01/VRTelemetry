# src/infrastructure/transport.py
"""The one place the real HTTP library is named (VRT-14).

``requests`` used to be imported at module scope in four files:
``session_uploader``, ``patient_sync_client``, ``heartbeat_client`` and the
container. VRT-12 put every *router's* outbound call behind
``container.http``, which is why the routers are testable offline -- but the
three clients kept their own reference, so the characterisation suite had to
reach in and replace two bound methods to stay off the network, with a comment
saying VRT-14 would fix it. This is that fix.

Naming the library in exactly one module is what makes the injection real
rather than decorative. A client that can fall back to a module-level
``requests`` when nothing is passed will do so the first time someone forgets,
and the test that was supposed to be offline goes to the network instead --
silently, because an unreachable server and a stub that raises look identical
from the assertion's side.
"""

from __future__ import annotations

from typing import cast

from src.application.ports import HttpClient


def default_http_client() -> HttpClient:
    """The production HTTP client.

    Imported inside the function rather than at module scope: importing this
    module must stay free of side effects, and ``requests`` initialises its
    adapters and TLS stack on import (see
    ``tests/unit/test_no_import_time_io.py``).

    Returns:
        The ``requests`` module, which satisfies :class:`HttpClient`
        structurally. The cast is the one place this correspondence is
        asserted; ``tests/unit/test_transport.py`` checks it holds.
    """
    import requests

    return cast(HttpClient, requests)
