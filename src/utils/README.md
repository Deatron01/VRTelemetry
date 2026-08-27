#   Init   Doc Auto Installer Doc Hardware Monitor Doc Logger Doc System Profiler Doc

#   Init   Doc

### Purpose
This module serves as the entry point for the system utilities layer, aggregating cross-cutting concerns like logging infrastructure and hardware monitoring. It provides a clean, unified namespace for importing essential operational helpers required throughout the application.

### Key Components / Key Classes / Key Exports
- **`setup_logging`**: Function to initialize and configure the centralized logging infrastructure.
- **`logger`**: Pre-configured logger instance ready for immediate use across modules.
- **`HardwareMonitor`**: Daemon/utility class responsible for tracking system resource usage and hardware states.

### Integration Points
It interfaces with core application layers by exposing standardized logging and diagnostic primitives, enabling other modules to record events and monitor host hardware metrics reliably.

---

# Auto Installer Doc

### Purpose
This module provides automated environment verification and dependency management by checking for a requirements file and installing necessary Python packages. It ensures the runtime environment is correctly configured before application initialization.

### Key Components / Key Classes / Key Exports
- **`verify_and_install_dependencies`**: Executes environment compliance checks, locates the requirements file, and invokes pip to install missing dependencies.

### Integration Points
Interacts with the filesystem to locate the project's 'requirements.txt' file at the workspace root, uses the host's Python interpreter and pip subsystem via subprocess execution, and interfaces with the standard logging module.

---

# Hardware Monitor Doc

### Purpose
The HardwareMonitor module provides a decoupled, low-frequency background poller for gathering system and hardware metrics like CPU utilization. It runs on a dedicated daemon thread to ensure high-frequency loops, such as OpenXR processing, remain uninterrupted by heavy or blocking OS calls.

### Key Components / Key Classes / Key Exports
- **`HardwareMonitor`**: Manages a background thread to periodically sample hardware states, exposing thread-safe metrics such as CPU usage and voice decibels.
- **`HardwareMonitor.start`**: Initializes and boots the background daemon thread at the specified target frequency.
- **`HardwareMonitor.stop`**: Gracefully signals the background thread to halt and joins the thread with a timeout.
- **`HardwareMonitor._poll_loop`**: Internal loop executing low-frequency metric extractions via `psutil` and applying error handling.

### Integration Points
This module integrates directly with the standard library `threading` and `time` modules, as well as the external `psutil` library for performance tracking. It is designed to expose state variables that can be safely read by downstream consumers like a BiometricSynchronizer or application telemetry systems.

---

# Logger Doc

### Purpose
This module provides a robust, thread-safe logging infrastructure for the application, targeting both standard output and persistent log files. It manages both global engine logs and isolated, session-specific log files for detailed telemetry capture.

### Key Components / Key Classes / Key Exports
- **`setup_logging`**: Configures the root logger with custom formatting, console handlers, and a global file handler, while suppressing overly verbose third-party logs.
- **`attach_session_log_capture`**: Attaches an additional file handler scoped specifically to a single recording session to capture focused runtime events.
- **`detach_session_log_capture`**: Safely flushes, closes, and detaches the session-specific log handler upon completion of a session.
- **`logger`**: A pre-configured module-level logger instance (`VRTelemetry`) for standard framework imports.

### Integration Points
This module integrates directly with Python's built-in `logging` ecosystem, standard output streams (`sys.stdout`), and the local filesystem via `pathlib` to create necessary log directories and files.

---

# System Profiler Doc

### Purpose
The system_profiler module captures host machine characteristics, environment details, and hardware telemetry snapshots at session start and during active execution. It provides essential metadata for session contexts under consented data-collection scopes while maintaining robust fallbacks when optional dependencies like psutil are missing.

### Key Components / Key Classes / Key Exports
- **`collect_system_profile`**: Gathers a comprehensive static snapshot of the OS, architecture, memory, CPU specs, disk stats, battery, and GPU info.
- **`collect_runtime_snapshot`**: Performs a lightweight, periodic poll of CPU and RAM utilization percentages during active sessions.
- **`_collect_gpu_info`**: Executes safe, platform-specific CLI probes (wmic, lspci, system_profiler) on a best-effort basis to identify available GPUs.

### Integration Points
This module integrates with standard Python platform libraries, the psutil external package when available, subprocess commands for hardware probing, and the broader application telemetry pipeline to enrich session metadata.

---

---
