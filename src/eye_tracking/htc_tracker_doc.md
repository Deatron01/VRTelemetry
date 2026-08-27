### Purpose
This module implements an eye-tracking driver specifically tailored for HTC hardware within an OpenXR environment. It manages the lifecycle of HTC facial tracking and standard eye gaze interaction extensions to harvest fine-grained eye state, pupil metrics, and spatial gaze vectors.

### Key Components / Key Classes / Key Exports
- **`HTCEyeTrackingDriver`**: Concrete implementation of `IEyeTrackingDriver` that handles OpenXR session binding, extension function lookups, frame telemetry population, and resource cleanup.
- **`initialize`**: Sets up the HTC Facial Tracker and OpenXR gaze action sets, configuring interaction profiles for spatial tracking.
- **`populate_frame`**: Samples blendshapes for eye closure/pupil indicators and captures spatial orientation/position vectors into a `TelemetryFrame`.
- **`shutdown`**: Releases OpenXR spaces, action sets, and underlying HTC facial tracking resources cleanly.

### Integration Points
This module integrates directly with the `EyeTrackingFactory` by registering itself as a driver via decorator-like execution, interacts with OpenXR runtime layers through the `xr` library via ctypes, and feeds data into the core system's `TelemetryFrame` structures.
