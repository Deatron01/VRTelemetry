from abc import ABC, abstractmethod
from typing import Optional
from src.core.datatypes import TelemetryFrame

class IVRBackend(ABC):
    """
    The base interface for all VR Hardware Abstraction Layers.
    Ensures absolute consistency across OpenXR, SteamVR, and Vendor-Specific APIs.
    """

    @abstractmethod
    def initialize(self) -> bool:
        """
        Attempts to bind to the VR runtime.
        Returns True if successful, False if the runtime is unavailable.
        """
        pass

    @abstractmethod
    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        """
        Queries all available sensors (HMD, Controllers, Eye Tracking).
        Must ALWAYS return a strictly typed TelemetryFrame.
        If a specific hardware feature is missing, it must zero out those specific values.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Gracefully releases hooks and unbinds from the VR runtime.
        """
        pass