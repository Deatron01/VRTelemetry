### Purpose
The `fb_social.py` module implements the Priority 100 biometric eye-tracking driver specifically tailored for Meta Quest Pro hardware via the OpenXR `XR_FB_eye_tracking_social` extension. It bypasses standard action-space focus limitations by directly querying individual left and right gaze vectors and confidence ratings using low-level OpenXR function pointers and ctypes.

### Key Components / Key Classes / Key Exports
- **`FBEyeTrackingSocialDriver`**: Core driver class implementing the `IEyeTrackingDriver` interface, handling hardware initialization, runtime frame population, and proper resource cleanup for Meta Quest Pro eye-tracking.
- **`__init__`**: Sets up internal tracking states and function pointer references.
- **`initialize`**: Resolves `xrCreateEyeTrackerFB` and `xrGetEyeGazesFB` instance procedure addresses and instantiates the eye tracker handle via ctypes.
- **`populate_frame`**: Queries the live gaze states for both left and right eyes at a given timestamp and maps positions, rotations, and confidences directly onto a `TelemetryFrame`.
- **`shutdown`**: Safely destroys the OpenXR eye tracker instance handle on termination.

### Integration Points
This module integrates directly with the OpenXR runtime environment (`xr`), `ctypes` for loading native function pointers, and registers itself into the application's driver architecture through `EyeTrackingFactory.register_driver`. It writes eye metrics straight into `TelemetryFrame` instances utilized by core telemetry systems.
