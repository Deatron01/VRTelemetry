### Purpose
This module defines the abstract hardware abstraction layer (HAL) interface for VR backends, enforcing standard data access contracts across dynamic runtime implementations. It ensures decoupled, consistent communication between the core telemetry loop and underlying VR hardware runtimes without spawning visible desktop windows.

### Key Classes / Key Exports
- **`IVRBackend`**: Abstract base class defining the standard interface for VR backends, requiring implementation of initialization, synchronous frame polling, and shutdown routines.
- **`initialize`**: Abstract method to establish runtime connections and bind spatial interaction profiles.
- **`poll_frame`**: Abstract method to synchronously fetch transform vectors and analog inputs as a `TelemetryFrame`.
- **`shutdown`**: Abstract method to release API handles and terminate the active session cleanly.

### Integration Points
This interface integrates directly with the core telemetry loop via concrete backend implementations and relies on the `TelemetryFrame` data class defined in `src.core.datatypes` to return standardized hardware states.
