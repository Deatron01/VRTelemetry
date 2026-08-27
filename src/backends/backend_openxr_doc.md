### Purpose
This module implements a production-grade OpenXR backend that handles headless execution for background telemetry services. It manages the complete OpenXR lifecycle, including instance creation, session management, action binding, spatial tracking for HMD and controllers, and integration with external biometric eye-tracking drivers.

### Key Components / Key Classes / Key Exports
- **`OpenXRBackend`**: Concrete implementation of `IVRBackend` that initializes OpenXR contexts, polls events, manages frame rendering loops, and delegates biometric data collection.
- **`_setup_actions`**: Internal helper configuring action sets, interaction profile bindings for controllers, and action spaces.
- **`_pump_events`**: Internal handler processing OpenXR runtime events and state changes like session ready or stopping states.

### Integration Points
Interfaces directly with the `xr` OpenXR ctypes bindings, `IVRBackend` interface definitions, `TelemetryFrame` structures, and the `EyeTrackingFactory` to discover and attach biometric tracking drivers.
