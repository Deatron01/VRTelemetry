### Purpose
This module implements the native LibOVR backend fallback for Oculus hardware within the VR telemetry system. It provides direct runtime access to Oculus HMD tracking, controller positions, and trigger inputs when OpenXR usage is undesirable.

### Key Components / Key Classes / Key Exports
- **`OculusBackend`**: Implements the `IVRBackend` interface, managing the LibOVR session lifecycle, hardware initialization, frame polling for headset and controller poses, and safe shutdown procedures.

### Integration Points
Interacts with the `IVRBackend` core interface contract, populates `TelemetryFrame` structures with extracted spatial and input data, logs events and errors through `src.utils.logger`, and conditionally integrates with the external `ovr` Python bindings.
