# src/core/exceptions.py

class VRTelemetryError(Exception):
    """Base exception class for all custom VRTelemetry framework errors."""
    pass

class GDPRConsentError(VRTelemetryError):
    """
    Raised when biometric tracking initialization is attempted without explicit 
    user consent, or if consent is programmatically revoked during a live session.
    Enforces compliance with biometric data collection regulations.
    """
    pass

class HardwareBindingError(VRTelemetryError):
    """
    Raised when the framework fails to attach to the OpenXR runtime or when 
    critical hardware extensions (like headless mode) are completely unavailable.
    """
    pass

class SynchronizationError(VRTelemetryError):
    """
    Raised when the producer-consumer ring buffer experiences catastrophic desynchronization 
    or queue exhaustion that cannot be mitigated by standard frame drops.
    """
    pass