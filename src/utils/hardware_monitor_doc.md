### Purpose
The HardwareMonitor module provides a decoupled, low-frequency background poller for gathering system and hardware metrics like CPU utilization. It runs on a dedicated daemon thread to ensure high-frequency loops, such as OpenXR processing, remain uninterrupted by heavy or blocking OS calls.

### Key Components / Key Classes / Key Exports
- **`HardwareMonitor`**: Manages a background thread to periodically sample hardware states, exposing thread-safe metrics such as CPU usage and voice decibels.
- **`HardwareMonitor.start`**: Initializes and boots the background daemon thread at the specified target frequency.
- **`HardwareMonitor.stop`**: Gracefully signals the background thread to halt and joins the thread with a timeout.
- **`HardwareMonitor._poll_loop`**: Internal loop executing low-frequency metric extractions via `psutil` and applying error handling.

### Integration Points
This module integrates directly with the standard library `threading` and `time` modules, as well as the external `psutil` library for performance tracking. It is designed to expose state variables that can be safely read by downstream consumers like a BiometricSynchronizer or application telemetry systems.
