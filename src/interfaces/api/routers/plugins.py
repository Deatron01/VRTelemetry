# src/interfaces/api/routers/plugins.py
"""Workstation-side plugin catalog, install/uninstall and status routes.

Part of the VR Telemetry Hub plugin architecture (VRT-26..31). This router
is the researcher-facing half: `src.plugin_manager.PluginManager` already
does the provisioning work (git clone, manifest validation, isolated venv,
subprocess lifecycle) via `Container.plugin_manager`; these routes just
expose a "browse the approved catalog / install / uninstall / check status"
surface a React panel in the Electron app can drive, instead of requiring a
researcher to hand-edit `plugins/registry.json` and restart the workstation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from src.interfaces.api.dependencies import CentralUrlDep, HttpDep, PluginManagerDep
from src.interfaces.api.schemas.plugins import (
    PluginInstallRequest,
    PluginStartRequest,
    PluginStopRequest,
    PluginUninstallRequest,
)
from src.plugin_manager import PluginManifestError
from src.plugin_manager.env_installer import PluginEnvironmentError
from src.plugin_manager.git_ops import PluginGitError
from src.plugin_manager.models import PluginStatus
from src.utils.logger import logger

router = APIRouter(tags=["plugins"])


def _status_dict(status: PluginStatus) -> dict[str, Any]:
    return {
        "plugin_id": status.plugin_id,
        "installed": status.installed,
        "enabled": status.enabled,
        "running": status.running,
        "pid": status.pid,
        "restarts": status.restarts,
        "last_exit_code": status.last_exit_code,
        "last_error": status.last_error,
        "name": status.name,
        "description": status.description,
        "version": status.version,
    }


def _fetch_catalog(http: Any, central_url: str) -> list[dict[str, Any]]:
    if not central_url:
        raise HTTPException(
            status_code=409,
            detail="No central server is configured. Set one under Settings before managing plugins.",
        )
    try:
        r = http.get(f"{central_url}/api/plugins/catalog", timeout=10)
    except http.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}") from e
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail="Could not fetch the plugin catalog.")
    result: list[dict[str, Any]] = r.json()
    return result


@router.get("/api/plugins/catalog")
def get_plugin_catalog(http: HttpDep, central_url: CentralUrlDep) -> list[dict[str, Any]]:
    """Proxy the Central Server's approved plugin catalog.

    A proxy rather than a client-side fetch of the central server directly:
    the researcher-facing UI only ever talks to this workstation's own
    loopback API (see `claude/hub-connection-and-networking.md`'s "Left
    alone deliberately" for why nothing else is exposed to it), and the hub
    address itself is a workstation setting the browser has no business
    knowing or being able to redirect.
    """
    return _fetch_catalog(http, central_url)


@router.get("/api/plugins/status")
def get_plugin_status(plugin_manager: PluginManagerDep) -> list[dict[str, Any]]:
    """Every plugin this workstation knows about -- installed, running or not."""
    return [_status_dict(status) for status in plugin_manager.status()]


@router.post("/api/plugins/install")
def install_plugin(
    payload: PluginInstallRequest,
    plugin_manager: PluginManagerDep,
    http: HttpDep,
    central_url: CentralUrlDep,
) -> dict[str, Any]:
    """Install one plugin named in the Central Server's catalog.

    Looks the plugin up in the catalog first -- never trusts a
    client-supplied repo_url; see `PluginInstallRequest`'s docstring -- then
    hands its catalog-provided `repo_url`/`ref` to
    `PluginManager.install_plugin`, which clones it, validates its
    `plugin.json` manifest (the "Flawless Setup" standard; see
    `src.plugin_manager.manifest`), builds its isolated venv, and starts it,
    all before this request returns.
    """
    catalog = _fetch_catalog(http, central_url)
    entry = next((p for p in catalog if p.get("plugin_id") == payload.plugin_id), None)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{payload.plugin_id}' is not in the approved plugin catalog.",
        )

    try:
        status = plugin_manager.install_plugin(
            plugin_id=entry["plugin_id"],
            repo_url=entry["repo_url"],
            ref=entry.get("ref", "main"),
        )
    except (PluginGitError, PluginEnvironmentError, PluginManifestError) as exc:
        # The plugin's own repository, manifest or dependencies are at
        # fault, not this request -- 422, with the reason, so the researcher
        # sees why "Install" didn't work instead of a bare 500.
        logger.error(f"Installing plugin '{payload.plugin_id}' failed: {exc}")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, ValueError, FileNotFoundError) as exc:
        logger.exception(f"Unexpected failure installing plugin '{payload.plugin_id}'")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _status_dict(status)


@router.post("/api/plugins/uninstall")
def uninstall_plugin(
    payload: PluginUninstallRequest, plugin_manager: PluginManagerDep
) -> dict[str, Any]:
    """Stop the plugin (if running) and remove it from `registry.json`."""
    existed = plugin_manager.uninstall_plugin(payload.plugin_id)
    if not existed:
        raise HTTPException(status_code=404, detail=f"'{payload.plugin_id}' is not installed.")
    return {"ok": True, "plugin_id": payload.plugin_id}


@router.post("/api/plugins/start")
def start_plugin(payload: PluginStartRequest, plugin_manager: PluginManagerDep) -> dict[str, Any]:
    """(Re)start an installed plugin without re-cloning it from the catalog.

    The pause-button counterpart to `/uninstall`: a plugin stopped via
    `/stop` (or one whose process crashed past `max_restarts_per_hour`)
    keeps its git checkout, venv and registry entry, so bringing it back
    here doesn't need the Central Server's catalog at all -- unlike
    `/install`, which always looks the plugin up there.
    """
    try:
        status = plugin_manager.start_plugin(payload.plugin_id)
    except (PluginGitError, PluginEnvironmentError, PluginManifestError) as exc:
        logger.error(f"Starting plugin '{payload.plugin_id}' failed: {exc}")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, ValueError, FileNotFoundError) as exc:
        logger.exception(f"Unexpected failure starting plugin '{payload.plugin_id}'")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if status is None:
        raise HTTPException(status_code=404, detail=f"'{payload.plugin_id}' is not installed.")
    return _status_dict(status)


@router.post("/api/plugins/stop")
def stop_plugin(payload: PluginStopRequest, plugin_manager: PluginManagerDep) -> dict[str, Any]:
    """Stop an installed plugin's process, keeping its registry entry (and clone/venv) intact.

    Distinct from `/uninstall` on purpose -- this is a pause, not a delete;
    see `PluginManager.stop_plugin`.
    """
    status = plugin_manager.stop_plugin(payload.plugin_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"'{payload.plugin_id}' is not installed.")
    return _status_dict(status)
