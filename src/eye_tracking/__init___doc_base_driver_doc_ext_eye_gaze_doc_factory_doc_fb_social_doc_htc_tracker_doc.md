#   Init   Doc

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

---

# Base Driver Doc

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

---

# Ext Eye Gaze Doc

### Purpose
The `ext_eye_gaze.py` module implements the standard Khronos OpenXR extension driver for eye tracking (`XR_EXT_eye_gaze_interaction`) with priority 10. It captures cyclopean gaze data within an OpenXR overlay session, gracefully handling focus loss or blink interruptions when space validity bits drop.

### Key Components / Key Classes / Key Exports
- **`EXTEyeGazeDriver`**: Concrete implementation of `IEyeTrackingDriver` responsible for binding the `XR_EXT_eye_gaze_interaction` OpenXR extension, syncing actions, locating eye space, and mapping unified gaze ray vectors into the `TelemetryFrame` structure.

### Integration Points
This driver inherits from `IEyeTrackingDriver` and registers itself with the `EyeTrackingFactory` via module-level execution. It integrates directly with the OpenXR runtime using the `xr` binding library to interact with session handles, action sets, and application spaces.

---

# Factory Doc

### Purpose
The factory module provides dynamic capability resolution for eye-tracking drivers in the runtime execution environment. It enables the system to evaluate hardware and extension availability, automatically selecting and instantiating the highest-priority compatible biometric abstraction layer.

### Key Components / Key Classes / Key Exports
- **`EyeTrackingFactory`**: Manages driver registration, priority sorting, and instantiation of the best available eye-tracking driver based on runtime extensions.

### Integration Points
Interacts directly with implementations of `IEyeTrackingDriver` by registering them, querying their extension names and priorities, and returning an instantiated driver instance to callers within the broader eye-tracking subsystem.

---

# Fb Social Doc

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

---

# Htc Tracker Doc

### Purpose
This module implements an eye-tracking driver specifically tailored for HTC hardware within an OpenXR environment. It manages the lifecycle of HTC facial tracking and standard eye gaze interaction extensions to harvest fine-grained eye state, pupil metrics, and spatial gaze vectors.

### Key Components / Key Classes / Key Exports
- **`HTCEyeTrackingDriver`**: Concrete implementation of `IEyeTrackingDriver` that handles OpenXR session binding, extension function lookups, frame telemetry population, and resource cleanup.
- **`initialize`**: Sets up the HTC Facial Tracker and OpenXR gaze action sets, configuring interaction profiles for spatial tracking.
- **`populate_frame`**: Samples blendshapes for eye closure/pupil indicators and captures spatial orientation/position vectors into a `TelemetryFrame`.
- **`shutdown`**: Releases OpenXR spaces, action sets, and underlying HTC facial tracking resources cleanly.

### Integration Points
This module integrates directly with the `EyeTrackingFactory` by registering itself as a driver via decorator-like execution, interacts with OpenXR runtime layers through the `xr` library via ctypes, and feeds data into the core system's `TelemetryFrame` structures.

---
