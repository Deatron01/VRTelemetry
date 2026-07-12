# src/eye_tracking/__init__.py

"""
Vendor-Agnostic Biometric Tracker Abstractions.
Automatically resolves and instantiates the highest-fidelity eye-tracking 
OpenXR extension available at runtime.
"""

from .factory import EyeTrackingFactory
from .base_driver import IEyeTrackingDriver

# Import drivers to trigger their auto-registration with the factory
from .ext_eye_gaze import EXTEyeGazeDriver
from .fb_social import FBEyeTrackingSocialDriver
from .htc_tracker import HTCEyeTrackingDriver

__all__ = [
    "EyeTrackingFactory",
    "IEyeTrackingDriver",
    "EXTEyeGazeDriver",
    "FBEyeTrackingSocialDriver",
    "HTCEyeTrackingDriver"
]