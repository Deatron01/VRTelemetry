# src/interfaces/api/routers/licence.py
"""Licence activation and status.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

import hashlib
import platform
import uuid as uuid_lib
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from src.interfaces.api.dependencies import CentralUrlDep, HttpDep, LocalCacheDep
from src.interfaces.api.schemas.licence import LicenseActivateRequest
from src.utils.logger import logger

if TYPE_CHECKING:
    from src.interfaces.api.container import Container

router = APIRouter(tags=["licence"])


def get_hardware_fingerprint() -> str:
    """
    Stable-ish per-machine identifier. Not cryptographically bulletproof (MAC-based
    fingerprints can be spoofed), but sufficient for seat-counting against casual
    reuse rather than determined circumvention — matches the LAN-trust-level of
    everything else right now.
    """
    node = uuid_lib.getnode()
    return hashlib.sha256(f"{platform.system()}-{platform.node()}-{node}".encode()).hexdigest()


@router.get("/api/license/status")
def license_status(http: HttpDep, central_url: CentralUrlDep, local_cache: LocalCacheDep):
    state = local_cache.get_state()
    if not state:
        return {"activated": False}

    valid_offline = local_cache.is_valid_offline()

    # Try a live heartbeat if reachable; falls back to cached offline validity if not.
    try:
        r = http.post(
            f"{central_url}/license/heartbeat",
            data={
                "activation_id": state["activation_id"],
                "machine_label": state.get("machine_label") or "",
            },
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            local_cache.save(
                activation_id=state["activation_id"],
                license_key=state.get("license_key"),
                hardware_fingerprint=state.get("hardware_fingerprint"),
                # Prefer whatever license_id the server just handed back — this is
                # what lets an install stuck with a missing license_id (see the
                # activation bug fixed below) self-heal on the next poll instead
                # of staying broken until the researcher reactivates by hand.
                license_id=data.get("license_id") or state.get("license_id"),
                machine_label=state.get("machine_label"),
                server_expires_at=data.get("expires_at"),
            )
            return {"activated": True, "status": "active", "offline": False}
        else:
            local_cache.mark_revoked()
            return {"activated": True, "status": "revoked", "offline": False}
    except http.RequestException:
        if valid_offline:
            return {"activated": True, "status": "active", "offline": True}
        return {"activated": True, "status": "expired_offline_grace", "offline": True}


@router.post("/api/license/activate")
def license_activate(
    payload: LicenseActivateRequest,
    http: HttpDep,
    central_url: CentralUrlDep,
    local_cache: LocalCacheDep,
):
    fingerprint = get_hardware_fingerprint()
    try:
        r = http.post(
            f"{central_url}/license/activate",
            data={
                "license_key": payload.license_key,
                "hardware_fingerprint": fingerprint,
                "machine_label": payload.machine_label,
                "os_platform": platform.system(),
                "app_version": "1.0.0",
            },
            timeout=10,
        )
    except http.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}")

    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code, detail=r.json().get("detail", "activation_failed")
        )

    data = r.json()
    local_cache.save(
        activation_id=data["activation_id"],
        license_key=payload.license_key,
        hardware_fingerprint=fingerprint,
        license_id=data.get("license_id"),
        machine_label=payload.machine_label,
        server_expires_at=data.get("expires_at"),
    )
    return {"ok": True}


def repair_missing_license_id(container: Container) -> None:
    """
    Self-heal for installs already stuck with license_id=None in the local
    cache — a pre-existing bug where /api/license/activate never forwarded
    the license_id the central server's /license/activate response already
    included. Every session/log/patient upload has a *required* license_id
    form field server-side, so a machine in this state 422's on every single
    upload attempt until it re-activates or this repair runs. Safe to call on
    every boot: it's a no-op the instant license_id is already populated.

    Takes the container rather than reading module-level singletons: this runs
    from the application's lifespan, where there is no request to resolve
    ``Depends`` against, but there is very much an application (VRT-12).

    Args:
        container: The collaborators of the application being started.
    """
    local_cache = container.local_cache
    http = container.http
    state = local_cache.get_state()
    if not state or state.get("license_id") or not state.get("activation_id"):
        return
    try:
        r = http.post(
            f"{container.central_url()}/license/heartbeat",
            data={
                "activation_id": state["activation_id"],
                "machine_label": state.get("machine_label") or "",
            },
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning(
                f"license_id repair: heartbeat rejected ({r.status_code}), leaving as-is for now."
            )
            return
        license_id = r.json().get("license_id")
        if not license_id:
            logger.warning(
                "license_id repair: server heartbeat didn't return a license_id either — "
                "uploads will keep failing until this activation is investigated."
            )
            return
        local_cache.save(
            activation_id=state["activation_id"],
            license_key=state.get("license_key"),
            hardware_fingerprint=state.get("hardware_fingerprint"),
            license_id=license_id,
            machine_label=state.get("machine_label"),
            server_expires_at=state.get("server_expires_at"),
        )
        logger.info(
            f"Repaired missing license_id in local cache ({license_id}) — uploads should work now."
        )
    except http.RequestException as e:
        logger.debug(f"license_id repair skipped — central server unreachable: {e}")
