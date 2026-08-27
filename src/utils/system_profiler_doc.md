### Purpose
The system_profiler module captures host machine characteristics, environment details, and hardware telemetry snapshots at session start and during active execution. It provides essential metadata for session contexts under consented data-collection scopes while maintaining robust fallbacks when optional dependencies like psutil are missing.

### Key Components / Key Classes / Key Exports
- **`collect_system_profile`**: Gathers a comprehensive static snapshot of the OS, architecture, memory, CPU specs, disk stats, battery, and GPU info.
- **`collect_runtime_snapshot`**: Performs a lightweight, periodic poll of CPU and RAM utilization percentages during active sessions.
- **`_collect_gpu_info`**: Executes safe, platform-specific CLI probes (wmic, lspci, system_profiler) on a best-effort basis to identify available GPUs.

### Integration Points
This module integrates with standard Python platform libraries, the psutil external package when available, subprocess commands for hardware probing, and the broader application telemetry pipeline to enrich session metadata.
