# src/eye_tracking/base_driver.py

from abc import ABC, abstractmethod

import xr

from src.core.datatypes import TelemetryFrame


class IEyeTrackingDriver(ABC):
    """
    Vendor-agnostic hardware abstraction contract. Decouples the proprietary mapping
    of OpenXR extensions from the internal data model generation.
    """

    @abstractmethod
    def get_extension_name(self) -> str:
        """
        Returns the primary OpenXR extension identifier required by this driver.
        """
        pass

    @abstractmethod
    def get_additional_extensions(self) -> list[str]:
        """
        Returns an array of supplemental OpenXR extensions required for full capability.
        """
        pass

    @abstractmethod
    def get_priority(self) -> int:
        """
        Resolution priority (higher indicates stronger biometric fidelity/accuracy).
        """
        pass

    @abstractmethod
    def initialize(self, instance: xr.Instance, session: xr.Session, app_space: xr.Space) -> bool:
        """
        Binds the internal OpenXR action mappings to the active headless session contexts.
        """
        pass

    @abstractmethod
    def populate_frame(self, frame: TelemetryFrame, timestamp_ns: int) -> None:
        """
        Extracts real-time eye vectors, pupil dilations, and convergence data, directly
        mutating the supplied float32 TelemetryFrame tensor slice.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Discards active bindings and frees local resources.
        """
        pass
