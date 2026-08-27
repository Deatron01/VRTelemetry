### Purpose
This module serves as the entry point for the system utilities layer, aggregating cross-cutting concerns like logging infrastructure and hardware monitoring. It provides a clean, unified namespace for importing essential operational helpers required throughout the application.

### Key Components / Key Classes / Key Exports
- **`setup_logging`**: Function to initialize and configure the centralized logging infrastructure.
- **`logger`**: Pre-configured logger instance ready for immediate use across modules.
- **`HardwareMonitor`**: Daemon/utility class responsible for tracking system resource usage and hardware states.

### Integration Points
It interfaces with core application layers by exposing standardized logging and diagnostic primitives, enabling other modules to record events and monitor host hardware metrics reliably.
