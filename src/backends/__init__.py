# src/backends/__init__.py

"""
Hardware Abstraction Layer (HAL) for spatial contexts.
Handles interaction profiles and dynamic binding strategies.
"""

from .discovery import RuntimeCapabilityDiscovery
from .openxr_headless import OpenXRHeadlessBackend

__all__ = [
    "RuntimeCapabilityDiscovery",
    "OpenXRHeadlessBackend"
]