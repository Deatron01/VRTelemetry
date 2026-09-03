# src/interfaces/api/routers/config.py
"""Central server address configuration.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.

One thing genuinely changed in VRT-12, and it is a fix rather than a
regression: writing a new address here now takes effect immediately. The
uploaders used to capture the URL when ``dependencies`` was imported, so a
researcher who pointed the workstation at a different hub kept uploading to the
old one until the app was restarted, with no indication anything was wrong.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.interfaces.api.dependencies import CentralUrlDep, HttpDep, LocalCacheDep
from src.interfaces.api.schemas.auth import CentralUrlCheck, CentralUrlConfig

router = APIRouter(tags=["config"])


@router.get("/api/config/central-server")
def get_central_config(central_url: CentralUrlDep):
    return {"central_server_url": central_url}


@router.post("/api/config/central-server")
def set_central_config(payload: CentralUrlConfig, local_cache: LocalCacheDep):
    local_cache.set_config("central_server_url", payload.central_server_url)
    return {"ok": True, "central_server_url": payload.central_server_url}


@router.post("/api/config/central-server/check")
def check_central_config(
    payload: CentralUrlCheck,
    http: HttpDep,
    central_url: CentralUrlDep,
) -> dict[str, Any]:
    """Ask whether a hub address actually reaches a hub.

    The gap this fills: until now the first thing that told a researcher their
    hub address was wrong was a failed upload at the *end* of a recording. On a
    two-machine setup -- hub on one box, workstation on another -- that is the
    normal case rather than the exotic one, because the address involves an IP
    that changes, a port, and a firewall.

    Deliberately does not save. Checking and configuring are different acts, and
    an address that fails the check is still a legitimate thing to save: the hub
    may simply be switched off, and this application supports working without
    one.

    Args:
        payload: The address to test, or nothing to test the saved one.
        http: The container's HTTP client, so a test stays offline.
        central_url: The configured address, used when none is supplied.

    Returns:
        ``reachable`` plus, when something answered, what answered. ``service``
        is the discriminator worth reading: a workstation pointed at the wrong
        service on the right port gets a reply and would otherwise look
        connected.
    """
    url = (payload.central_server_url or central_url or "").rstrip("/")
    if not url:
        return {
            "reachable": False,
            "url": "",
            "detail": "No central server address is configured on this machine.",
        }

    try:
        response = http.get(f"{url}/health", timeout=5)
    except http.RequestException as exc:
        return {
            "reachable": False,
            "url": url,
            "detail": f"Could not reach {url}: {exc}",
        }

    if response.status_code != 200:
        return {
            "reachable": False,
            "url": url,
            "detail": (
                f"{url} answered with HTTP {response.status_code}. Something is "
                f"listening there, but it is not a VRTelemetry hub."
            ),
        }

    try:
        body = response.json()
    except ValueError:
        return {
            "reachable": False,
            "url": url,
            "detail": (
                f"{url} answered, but not with JSON. Something is listening "
                f"there, but it is not a VRTelemetry hub."
            ),
        }

    return {
        "reachable": True,
        "url": url,
        "service": body.get("service"),
        "version": body.get("version"),
        "database": body.get("database"),
        "healthy": bool(body.get("ok")),
    }
