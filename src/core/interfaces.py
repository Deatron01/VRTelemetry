# src/core/interfaces.py

from abc import ABC, abstractmethod

from src.core.datatypes import TelemetryFrame


class IVRBackend(ABC):
    """
    Abstract Hardware Abstraction Layer (HAL) interface enforcing standard data access
    contracts across dynamic runtime backends.
    """

    @abstractmethod
    def initialize(self) -> bool:
        """
        Establishes connections to runtime contexts and binds spatial interaction profiles.
        Must execute without spawning visible desktop windows.

        Returns:
            bool: True if context successfully bound, False otherwise.
        """
        pass

    @abstractmethod
    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        """
        Synchronously fetches the latest transform vectors and analog inputs from the active runtime.
        Expected to block execution tightly against the hardware's vsync/display timer.

        Args:
            frame_index (int): The current sequential index of the telemetry loop.

        Returns:
            TelemetryFrame: A populated 1D data class representing the exact hardware state.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Releases all open API handles, destroys spaces, and cleanly terminates
        the active runtime session.
        """
        pass
