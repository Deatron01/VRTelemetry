# src/interfaces/api/routers/config.py
"""Central server address configuration.

Moved from src/main.py. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.interfaces.api import dependencies as deps
from src.interfaces.api.schemas.auth import CentralUrlConfig

router = APIRouter(tags=["config"])


@router.get("/api/config/central-server")
def get_central_config():
    return {"central_server_url": deps.central_url()}


@router.post("/api/config/central-server")
def set_central_config(payload: CentralUrlConfig):
    deps.local_cache.set_config("central_server_url", payload.central_server_url)
    return {"ok": True, "central_server_url": payload.central_server_url}
