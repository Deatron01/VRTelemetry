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
