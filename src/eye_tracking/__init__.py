# src/eye_tracking/__init__.py

"""Vendor-agnostic biometric tracker abstractions.

Resolves and instantiates the highest-fidelity eye-tracking OpenXR
extension available at runtime.

Note: the concrete drivers register themselves with EyeTrackingFactory as a
side effect of being imported. Lazy re-export means that no longer happens
merely because this package was touched -- EyeTrackingFactory.create_best_driver
imports them explicitly instead, which is where the registration belongs.

Import surface note (VRT-5.1)
-----------------------------
The names below are re-exported **lazily**, via PEP 562 ``__getattr__``. They
used to be eager ``from .module import Name`` statements at import time, which
built a cycle:

    src.backends.__init__  ->  .openxr_headless
                           ->  src.core.interfaces
                           ->  src.core.__init__  ->  .engine
                           ->  src.backends.udp_receiver
                           ->  src.backends.__init__   (already initialising)

``pytest tests/unit/test_discovery.py`` on its own failed at collection with
"cannot import name 'OpenXRHeadlessBackend' from partially initialized module".
It only passed in a full run because some earlier test module happened to
import ``src.core`` first and warm the cache -- a test suite that depends on
collection order is a test suite that will break for someone eventually.

The eager imports also meant that touching *any* module in these packages
dragged in the whole dependency graph. ``from src.core.datatypes import
TelemetryFrame`` -- a pure dataclass with no hardware in it -- pulled in the
engine, every VR backend, and therefore ``xr`` and ``openvr``, so the unit
tests could not run on a machine without VR runtime bindings installed.

Lazy re-export keeps the public surface identical for anyone writing
``from src.eye_tracking import EyeTrackingFactory`` while removing both problems. Nothing in this
repository imports through these facades today; they are kept for external
consumers and for the documented API.

Proper layer boundaries, which remove the need for the facade at all, are
VRT-12 and VRT-14.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base_driver import IEyeTrackingDriver
    from .ext_eye_gaze import EXTEyeGazeDriver
    from .factory import EyeTrackingFactory
    from .fb_social import FBEyeTrackingSocialDriver
    from .htc_tracker import HTCEyeTrackingDriver

#: Public name -> the submodule that defines it.
_EXPORTS: dict[str, str] = {
    "EyeTrackingFactory": ".factory",
    "IEyeTrackingDriver": ".base_driver",
    "EXTEyeGazeDriver": ".ext_eye_gaze",
    "FBEyeTrackingSocialDriver": ".fb_social",
    "HTCEyeTrackingDriver": ".htc_tracker",
}

__all__ = [
    "EXTEyeGazeDriver",
    "EyeTrackingFactory",
    "FBEyeTrackingSocialDriver",
    "HTCEyeTrackingDriver",
    "IEyeTrackingDriver",
]


def __getattr__(name: str) -> Any:
    """Resolve a re-exported name on first access (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module, __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)
