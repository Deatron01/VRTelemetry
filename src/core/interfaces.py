from abc import ABC, abstractmethod
from src.core.datatypes import TelemetryFrame

class IVRBackend(ABC):
    """
    Abstract Hardware Abstraction Layer interface enforcing standard data access 
    contracts across runtime backends.
    """
    @abstractmethod
    def initialize(self) -> bool:
        """Establishes connections to runtime contexts and binds spaces."""
        pass

    @abstractmethod
    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        """Fetches the latest transform values from active runtimes."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Releases all open handlers and terminates runtime contexts."""
        pass