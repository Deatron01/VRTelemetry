### Purpose
The `ext_eye_gaze.py` module implements the standard Khronos OpenXR extension driver for eye tracking (`XR_EXT_eye_gaze_interaction`) with priority 10. It captures cyclopean gaze data within an OpenXR overlay session, gracefully handling focus loss or blink interruptions when space validity bits drop.

### Key Components / Key Classes / Key Exports
- **`EXTEyeGazeDriver`**: Concrete implementation of `IEyeTrackingDriver` responsible for binding the `XR_EXT_eye_gaze_interaction` OpenXR extension, syncing actions, locating eye space, and mapping unified gaze ray vectors into the `TelemetryFrame` structure.

### Integration Points
This driver inherits from `IEyeTrackingDriver` and registers itself with the `EyeTrackingFactory` via module-level execution. It integrates directly with the OpenXR runtime using the `xr` binding library to interact with session handles, action sets, and application spaces.
