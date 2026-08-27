# VRTelemetry Exceptions Module

This module defines the custom exception hierarchy for the VRTelemetry framework (`src.core.exceptions`). These exceptions are used to signal critical errors related to compliance, hardware initialization, and data synchronization.

## Exceptions

- `VRTelemetryError`: The base exception class from which all framework-specific exceptions inherit.
- `GDPRConsentError`: Raised when biometric tracking is attempted without explicit user consent or if consent is revoked during a session, ensuring compliance with data protection regulations.
- `HardwareBindingError`: Raised when the framework fails to attach to the OpenXR runtime or when critical hardware extensions (such as headless mode) are unavailable.
- `SynchronizationError`: Raised during catastrophic desynchronization or queue exhaustion in the producer-consumer ring buffer that cannot be mitigated by standard frame drops.