class VRTelemetryError(Exception):
    """Base exception class for all VRTelemetry-specific errors."""
    pass

class HardwareBindingError(VRTelemetryError):
    """Raised when a backend (OpenXR/SteamVR/Oculus) fails to initialize or find a headset."""
    pass

class TelemetryQueueOverflowError(VRTelemetryError):
    """Raised when the asynchronous Parquet I/O thread cannot keep up with the 120Hz polling rate."""
    pass

class SensorDataMissingError(VRTelemetryError):
    """Raised when critical spatial data is completely unavailable, prompting a fallback frame generation."""
    pass

class GDPRConsentError(VRTelemetryError):
    """Raised when biometric data collection is attempted without explicit user consent."""
    pass

class DependencyMissingError(VRTelemetryError):
    """Raised when required DLLs or Python packages are not found on the host system."""
    pass