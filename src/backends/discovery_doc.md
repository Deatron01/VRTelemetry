### Purpose
This module implements a stateless evaluator designed to probe the active OpenXR runtime instance and extract critical hardware parameters, capabilities, and system metadata. It acts as the primary discovery mechanism for checking hardware support such as eye tracking, face tracking, and body tracking according to runtime specifications.

### Key Components / Key Classes / Key Exports
- **`RuntimeCapabilityDiscovery`**: Stateless utility class encapsulating hardware and extension probing logic via the pyopenxr bindings.
- **`extract_static_hardware_metadata()`**: Queries available OpenXR extensions, evaluates biometric capabilities, initializes a temporary runtime instance to identify the HMD model and runtime version, and safely cleans up resources.

### Integration Points
This module integrates directly with the external `pyopenxr` library to query native OpenXR system properties and extension properties. It is typically invoked during application initialization or telemetry boot sequences to populate runtime configuration states and requirement compliance dictionaries.
