"""Typed configuration for VRTelemetry (VRT-6).

Exposes :func:`get_settings`. Import that, never a literal path.
"""

from src.config.settings import Settings, get_settings, reset_settings_cache

__all__ = ["Settings", "get_settings", "reset_settings_cache"]
