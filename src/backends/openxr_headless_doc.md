### Purpose
This module implements a headless OpenXR backend abstraction for VR telemetry and eye-tracking applications. It supports native MND headless execution or falls back gracefully to an invisible Direct3D 11 device context on Windows runtimes (like Oculus or SteamVR) when the native headless extension is missing, enabling silent background execution without a visible window.

### Key Components / Key Classes / Key Exports
- **`OpenXRHeadlessBackend`**: Concrete implementation of the `IVRBackend` interface responsible for initializing the OpenXR instance, setting up actions and spaces, managing frame telemetry loops, and cleaning up resources.
- **`_create_d3d11_binding`**: Internal helper method that instantiates an invisible D3D11 graphics context using ctypes to satisfy Windows XR runtimes requiring graphics bindings.
- **`poll_frame`**: Samples telemetry data per frame including HMD poses, controller tracking, triggers, and biometrics via optional eye-tracking drivers.

### Integration Points
This module integrates directly with the `IVRBackend` core interface, `TelemetryFrame` structures, and `EyeTrackingFactory` to discover and initialize eye-tracking drivers. It interacts with the underlying OpenXR runtime libraries (`xr`), the Windows D3D11 graphics API, and system interaction profiles.
