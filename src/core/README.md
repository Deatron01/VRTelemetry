#   Init   Doc Datatypes Doc Engine Doc Exceptions Doc Interfaces Doc Synchronizer Doc

#   Init   Doc

### Purpose
This module serves as the primary entry point for the core telemetry execution layer of the application. It aggregates and exposes fundamental engine components, data models, synchronization primitives, and custom domain exceptions. By centralizing these exports, it provides a clean, unified interface for outer layers to interact with the core telemetry system.

### Key Components / Key Classes / Key Exports
- **`TelemetryEngine`**: The core orchestrator engine responsible for managing the execution lifecycle and flow of telemetry data.
- **`TelemetryFrame`**: The standard data model representing a single captured telemetry data structure.
- **`BiometricSynchronizer`**: A high-frequency synchronization queue component handling biometric data streams.
- **`IVRBackend`**: An interface definition establishing contracts for backend integrations.
- **`GDPRConsentError` / `HardwareBindingError`**: Custom domain-specific exceptions handling compliance and hardware constraint violations.

### Integration Points
This module integrates directly with underlying core submodules (`engine`, `datatypes`, `synchronizer`, `interfaces`, and `exceptions`) to bundle their functionality. It acts as the facade used by external application modules, controllers, and entry scripts to instantiate and orchestrate telemetry processing.

---

# Datatypes Doc

The `datatypes.py` module defines the core data structures used for high-frequency (120Hz) telemetry recording in virtual reality applications. It features the memory-isolated `TelemetryFrame` dataclass which uses `__slots__` to ensure O(1) lookups and prevent dynamic memory allocation overhead during runtime loops. The class encapsulates spatial and kinematic tracking for HMD and dual controllers, unified eye-tracking metrics, biometrics, hardware/system status, and virtual environment states. Key methods include `to_tuple()` for flattening parameters to match PyArrow memory table formats and `create_empty()` for generating fallback default values during hardware connection losses.

---

# Engine Doc

The `engine.py` module defines the `TelemetryEngine` class, which serves as the production telemetry orchestrator. It manages deterministic synchronization between hardware pacing loops (OpenXR, SteamVR, Oculus, or UDP Quest receiver) and asynchronous I/O storage subsystems. Key responsibilities include checking GDPR consent, coordinating session lifecycles, managing multi-threaded event loops for async writing, monitoring hardware capabilities, uploading session files to a central server, and executing clean teardowns.

---

# Exceptions Doc

# VRTelemetry Exceptions Module

This module defines the custom exception hierarchy for the VRTelemetry framework (`src.core.exceptions`). These exceptions are used to signal critical errors related to compliance, hardware initialization, and data synchronization.

## Exceptions

- `VRTelemetryError`: The base exception class from which all framework-specific exceptions inherit.
- `GDPRConsentError`: Raised when biometric tracking is attempted without explicit user consent or if consent is revoked during a session, ensuring compliance with data protection regulations.
- `HardwareBindingError`: Raised when the framework fails to attach to the OpenXR runtime or when critical hardware extensions (such as headless mode) are unavailable.
- `SynchronizationError`: Raised during catastrophic desynchronization or queue exhaustion in the producer-consumer ring buffer that cannot be mitigated by standard frame drops.

---

# Interfaces Doc

### Purpose
This module defines the abstract hardware abstraction layer (HAL) interface for VR backends, enforcing standard data access contracts across dynamic runtime implementations. It ensures decoupled, consistent communication between the core telemetry loop and underlying VR hardware runtimes without spawning visible desktop windows.

### Key Classes / Key Exports
- **`IVRBackend`**: Abstract base class defining the standard interface for VR backends, requiring implementation of initialization, synchronous frame polling, and shutdown routines.
- **`initialize`**: Abstract method to establish runtime connections and bind spatial interaction profiles.
- **`poll_frame`**: Abstract method to synchronously fetch transform vectors and analog inputs as a `TelemetryFrame`.
- **`shutdown`**: Abstract method to release API handles and terminate the active session cleanly.

### Integration Points
This interface integrates directly with the core telemetry loop via concrete backend implementations and relies on the `TelemetryFrame` data class defined in `src.core.datatypes` to return standardized hardware states.

---

# Synchronizer Doc

### Purpose
BiometricSynchronizer provides a lock-free ring buffer architecture designed to support 144Hz zero-loss telemetry transport. It decouples high-frequency OpenXR rendering and hardware threads from disk-writing I/O tasks to prevent tracking stalls and ensure consistent performance.

### Key Components / Key Classes / Key Exports
- **`BiometricSynchronizer`**: Core class managing a thread-safe `deque` buffer, asynchronous consumer loops, and graceful frame flushing during shutdown.
- **`push_frame`**: Non-blocking method invoked by the hardware thread to instantly capture and buffer telemetry frames.
- **`_consume_loop`**: Asynchronous background worker that batches buffered frame data and forwards it to disk storage components.

### Integration Points
Interfaces directly with `AsyncParquetWriter` for disk persistence, `HardwareMonitor` for telemetry tracking, and an `asyncio` event loop to manage background flushing operations.

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
core/
├── README.md
├── __init__.py
├── datatypes.py
├── engine.py
├── exceptions.py
├── interfaces.py
└── synchronizer.py
```