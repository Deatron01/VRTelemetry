### Purpose
This module defines the vendor-agnostic hardware abstraction interface for eye tracking drivers within the application. It decouples the proprietary mapping of OpenXR extensions from internal data model generation, allowing the system to support multiple hardware vendors uniformly.

### Key Components / Key Classes / Key Exports
- **`IEyeTrackingDriver`**: Abstract base class defining the mandatory contract for all eye-tracking hardware implementations, including initialization, telemetry population, and resource cleanup.
- **`get_extension_name`**: Abstract method returning the primary OpenXR extension identifier required by the driver.
- **`get_additional_extensions`**: Abstract method returning supplemental OpenXR extensions needed for full capability.
- **`get_priority`**: Abstract method determining driver resolution priority based on biometric fidelity and accuracy.
- **`initialize`**: Abstract method that binds internal OpenXR action mappings to active headless session contexts.
- **`populate_frame`**: Abstract method that extracts real-time eye vectors, pupil dilations, and convergence data to mutate a TelemetryFrame tensor slice.
- **`shutdown`**: Abstract method that discards active bindings and frees local hardware resources.

### Integration Points
This interface integrates directly with the OpenXR runtime via `xr.Instance`, `xr.Session`, and `xr.Space` parameters during initialization, and populates `TelemetryFrame` structures used downstream by telemetry and analytics pipelines.
