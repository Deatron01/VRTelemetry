### Purpose
This module provides vendor-agnostic biometric tracker abstractions for OpenXR eye-tracking implementations. It automatically resolves and instantiates the highest-fidelity eye-tracking extension available at runtime, streamlining hardware integration.

### Key Components / Key Classes / Key Exports
- **`EyeTrackingFactory`**: Factory class responsible for resolving and instantiating the appropriate eye-tracking driver based on runtime availability.
- **`IEyeTrackingDriver`**: Abstract base interface defining the standard contract that all vendor-specific eye-tracking drivers must implement.
- **`EXTEyeGazeDriver`**: Vendor-specific driver implementation for the standard OpenXR EXT eye gaze extension.
- **`FBEyeTrackingSocialDriver`**: Vendor-specific driver implementation for Meta/Facebook social eye-tracking features.
- **`HTCEyeTrackingDriver`**: Vendor-specific driver implementation for HTC eye-tracking hardware.

### Integration Points
This module integrates directly with underlying OpenXR runtime extensions by importing concrete driver implementations which self-register with the `EyeTrackingFactory` upon initialization.
