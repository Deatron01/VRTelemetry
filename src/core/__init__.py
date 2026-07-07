# src/core/__init__.py

"""
Telemetry Core Execution Module
Exposes the orchestrator engine, data models, and high-frequency synchronization queues.
"""

from .engine import TelemetryEngine
from .datatypes import TelemetryFrame
from .synchronizer import BiometricSynchronizer
from .interfaces import IVRBackend
from .exceptions import GDPRConsentError, HardwareBindingError

__all__ = [
    "TelemetryEngine",
    "TelemetryFrame",
    "BiometricSynchronizer",
    "IVRBackend",
    "GDPRConsentError",
    "HardwareBindingError"
]