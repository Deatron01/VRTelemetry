### Purpose
This module provides a robust, thread-safe logging infrastructure for the application, targeting both standard output and persistent log files. It manages both global engine logs and isolated, session-specific log files for detailed telemetry capture.

### Key Components / Key Classes / Key Exports
- **`setup_logging`**: Configures the root logger with custom formatting, console handlers, and a global file handler, while suppressing overly verbose third-party logs.
- **`attach_session_log_capture`**: Attaches an additional file handler scoped specifically to a single recording session to capture focused runtime events.
- **`detach_session_log_capture`**: Safely flushes, closes, and detaches the session-specific log handler upon completion of a session.
- **`logger`**: A pre-configured module-level logger instance (`VRTelemetry`) for standard framework imports.

### Integration Points
This module integrates directly with Python's built-in `logging` ecosystem, standard output streams (`sys.stdout`), and the local filesystem via `pathlib` to create necessary log directories and files.
