"""Typed configuration for VRTelemetry (VRT-6).

Exposes :func:`get_settings`. Import that, never a literal path.

The individual section models are exported too, because building a
:class:`Settings` for a temporary data root -- which is what every test and the
composition root's ``settings`` parameter do -- means constructing a
:class:`PathSettings` (VRT-12).
"""

from src.config.settings import (
    AcquisitionSettings,
    ApiSettings,
    CentralServerSettings,
    ConsentSettings,
    HubSettings,
    PathSettings,
    Settings,
    SyncSettings,
    get_settings,
    reset_settings_cache,
)

__all__ = [
    "AcquisitionSettings",
    "ApiSettings",
    "CentralServerSettings",
    "ConsentSettings",
    "HubSettings",
    "PathSettings",
    "Settings",
    "SyncSettings",
    "get_settings",
    "reset_settings_cache",
]
