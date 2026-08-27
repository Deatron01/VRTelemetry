### Purpose
This module implements a native OpenVR backend fallback using the OpenVR overlay architecture. It allows telemetry and pose extraction directly from SteamVR-native headsets by bypassing OpenXR action system focus requirements.

### Key Components / Key Classes / Key Exports
- **`matrix_to_quaternion`**: Converts an OpenVR 3x4 transformation matrix into a normalized quaternion tuple (x, y, z, w).
- **`SteamVROverlayBackend`**: Implements the `IVRBackend` interface to manage OpenVR overlay initialization, device pose and controller data polling, and context teardown.

### Integration Points
This module integrates with the `openvr` Python package to interface with SteamVR runtimes. It conforms to the `IVRBackend` interface from `src.core.interfaces` and produces `TelemetryFrame` structures defined in `src.core.datatypes`.
