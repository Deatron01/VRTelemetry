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

from fastapi import APIRouter

from src.interfaces.api.dependencies import CentralUrlDep, LocalCacheDep
from src.interfaces.api.schemas.auth import CentralUrlConfig

router = APIRouter(tags=["config"])


@router.get("/api/config/central-server")
def get_central_config(central_url: CentralUrlDep):
    return {"central_server_url": central_url}


@router.post("/api/config/central-server")
def set_central_config(payload: CentralUrlConfig, local_cache: LocalCacheDep):
    local_cache.set_config("central_server_url", payload.central_server_url)
    return {"ok": True, "central_server_url": payload.central_server_url}
