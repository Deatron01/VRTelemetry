# src/plugin_manager/__init__.py
"""Provisioning and running out-of-process plugins (git clone, isolated
virtual environments, subprocess lifecycle, `plugin.json` manifest
validation) for the VR Telemetry Hub's Event Router
(`src/interfaces/api/event_router.py`).

A plugin is never trusted with anything the recording loop depends on --
see `src.storage.tee_sink.TeeFrameSink`'s docstring. This package is
provisioning and process supervision only; it has no import of
`src.application` and no way to affect a running recording. The one
exception is `src.core.plugin_protocol.PROTOCOL_VERSION` -- a bare integer
constant, not the engine -- imported by `manifest.py` so a plugin's declared
protocol version is checked against the same number the Event Router stamps
onto every message; see that module's docstring for why it lives in
`src.core` rather than in either side that reads it.
"""

from src.plugin_manager.manager import PluginManager, load_registry
from src.plugin_manager.manifest import PluginManifest, PluginManifestError, load_manifest
from src.plugin_manager.models import PluginSource, PluginSpec, PluginStatus

__all__ = [
    "PluginManager",
    "PluginManifest",
    "PluginManifestError",
    "PluginSource",
    "PluginSpec",
    "PluginStatus",
    "load_manifest",
    "load_registry",
]
