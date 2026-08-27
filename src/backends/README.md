#   Init   Doc Backend Ocolus Doc Backend Openxr Doc Backend Steamvr Doc Discovery Doc Openxr Headless Doc Udp Receiver Doc

#   Init   Doc

### Purpose
This module serves as the entry point for the Hardware Abstraction Layer (HAL) within the spatial computing system. It exposes core backend components responsible for managing interaction profiles, runtime capability discovery, and headless spatial rendering strategies.

### Key Components / Key Classes / Key Exports
- **`RuntimeCapabilityDiscovery`**: Discovers and enumerates available spatial runtimes and hardware capabilities on the host system.
- **`OpenXRHeadlessBackend`**: Provides a headless OpenXR backend implementation for rendering and tracking without physical display hardware.

### Integration Points
It integrates directly with underlying OpenXR runtimes and operating system hardware interfaces, providing a unified abstraction layer that upper-level spatial context modules consume.

---

# Backend Ocolus Doc

### Purpose
This module implements the native LibOVR backend fallback for Oculus hardware within the VR telemetry system. It provides direct runtime access to Oculus HMD tracking, controller positions, and trigger inputs when OpenXR usage is undesirable.

### Key Components / Key Classes / Key Exports
- **`OculusBackend`**: Implements the `IVRBackend` interface, managing the LibOVR session lifecycle, hardware initialization, frame polling for headset and controller poses, and safe shutdown procedures.

### Integration Points
Interacts with the `IVRBackend` core interface contract, populates `TelemetryFrame` structures with extracted spatial and input data, logs events and errors through `src.utils.logger`, and conditionally integrates with the external `ovr` Python bindings.

---

# Backend Openxr Doc

### Purpose
This module implements a production-grade OpenXR backend that handles headless execution for background telemetry services. It manages the complete OpenXR lifecycle, including instance creation, session management, action binding, spatial tracking for HMD and controllers, and integration with external biometric eye-tracking drivers.

### Key Components / Key Classes / Key Exports
- **`OpenXRBackend`**: Concrete implementation of `IVRBackend` that initializes OpenXR contexts, polls events, manages frame rendering loops, and delegates biometric data collection.
- **`_setup_actions`**: Internal helper configuring action sets, interaction profile bindings for controllers, and action spaces.
- **`_pump_events`**: Internal handler processing OpenXR runtime events and state changes like session ready or stopping states.

### Integration Points
Interfaces directly with the `xr` OpenXR ctypes bindings, `IVRBackend` interface definitions, `TelemetryFrame` structures, and the `EyeTrackingFactory` to discover and attach biometric tracking drivers.

---

# Backend Steamvr Doc

### Purpose
This module implements a native OpenVR backend fallback using the OpenVR overlay architecture. It allows telemetry and pose extraction directly from SteamVR-native headsets by bypassing OpenXR action system focus requirements.

### Key Components / Key Classes / Key Exports
- **`matrix_to_quaternion`**: Converts an OpenVR 3x4 transformation matrix into a normalized quaternion tuple (x, y, z, w).
- **`SteamVROverlayBackend`**: Implements the `IVRBackend` interface to manage OpenVR overlay initialization, device pose and controller data polling, and context teardown.

### Integration Points
This module integrates with the `openvr` Python package to interface with SteamVR runtimes. It conforms to the `IVRBackend` interface from `src.core.interfaces` and produces `TelemetryFrame` structures defined in `src.core.datatypes`.

---

# Discovery Doc

### Purpose
This module implements a stateless evaluator designed to probe the active OpenXR runtime instance and extract critical hardware parameters, capabilities, and system metadata. It acts as the primary discovery mechanism for checking hardware support such as eye tracking, face tracking, and body tracking according to runtime specifications.

### Key Components / Key Classes / Key Exports
- **`RuntimeCapabilityDiscovery`**: Stateless utility class encapsulating hardware and extension probing logic via the pyopenxr bindings.
- **`extract_static_hardware_metadata()`**: Queries available OpenXR extensions, evaluates biometric capabilities, initializes a temporary runtime instance to identify the HMD model and runtime version, and safely cleans up resources.

### Integration Points
This module integrates directly with the external `pyopenxr` library to query native OpenXR system properties and extension properties. It is typically invoked during application initialization or telemetry boot sequences to populate runtime configuration states and requirement compliance dictionaries.

---

# Openxr Headless Doc

### Purpose
This module implements a headless OpenXR backend abstraction for VR telemetry and eye-tracking applications. It supports native MND headless execution or falls back gracefully to an invisible Direct3D 11 device context on Windows runtimes (like Oculus or SteamVR) when the native headless extension is missing, enabling silent background execution without a visible window.

### Key Components / Key Classes / Key Exports
- **`OpenXRHeadlessBackend`**: Concrete implementation of the `IVRBackend` interface responsible for initializing the OpenXR instance, setting up actions and spaces, managing frame telemetry loops, and cleaning up resources.
- **`_create_d3d11_binding`**: Internal helper method that instantiates an invisible D3D11 graphics context using ctypes to satisfy Windows XR runtimes requiring graphics bindings.
- **`poll_frame`**: Samples telemetry data per frame including HMD poses, controller tracking, triggers, and biometrics via optional eye-tracking drivers.

### Integration Points
This module integrates directly with the `IVRBackend` core interface, `TelemetryFrame` structures, and `EyeTrackingFactory` to discover and initialize eye-tracking drivers. It interacts with the underlying OpenXR runtime libraries (`xr`), the Windows D3D11 graphics API, and system interaction profiles.

---

# Udp Receiver Doc

### Purpose
This module implements a high-performance asynchronous UDP receiver designed to capture 64-byte binary telemetry structs generated by the Quest Pro native overlay. It provides low-overhead packet parsing and mapping directly into standard internal telemetry data structures.

### Key Components / Key Classes / Key Exports
- **`NativeQuestHarvesterProtocol`**: An asyncio DatagramProtocol that validates packet lengths, unpacks little-endian binary structures, normalizes confidence metrics, and feeds parsed data into the biometric synchronizer.
- **`NativeQuestReceiver`**: Orchestrator class responsible for setting up, binding, and safely closing the asynchronous UDP server socket endpoint.

### Integration Points
It integrates directly with Python's `asyncio` loop for non-blocking network I/O, relies on `src.core.datatypes.TelemetryFrame` for data representation, and feeds parsed frames into `src.core.synchronizer.BiometricSynchronizer` for lock-free multi-stream synchronization.

---

---
