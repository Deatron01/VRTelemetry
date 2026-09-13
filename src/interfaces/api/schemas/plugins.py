# src/interfaces/api/schemas/plugins.py
"""Wire models for the Workstation API's plugin catalog/install/status routes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PluginInstallRequest(BaseModel):
    """Install one plugin named in the Central Server's catalog.

    Only `plugin_id` is required: `repo_url` and `ref` are looked up from the
    catalog server-side (`POST /api/plugins/install`'s implementation), not
    trusted from the client -- the whole point of an *approved* catalog is
    that a researcher installs from it by name, rather than pasting a git
    URL nobody has vetted into a form.
    """

    plugin_id: str = Field(min_length=1)


class PluginUninstallRequest(BaseModel):
    plugin_id: str = Field(min_length=1)


class PluginStartRequest(BaseModel):
    """Start (or restart) an already-installed plugin. See `PluginManager.start_plugin`."""

    plugin_id: str = Field(min_length=1)


class PluginStopRequest(BaseModel):
    """Stop an installed plugin's process without uninstalling it. See `PluginManager.stop_plugin`."""

    plugin_id: str = Field(min_length=1)
