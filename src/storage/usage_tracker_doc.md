### Purpose
This module tracks application-level telemetry such as page views, session start and stop actions, and export usage. It is intentionally kept separate from biometric session metadata to adhere to distinct consent scopes and application lifecycles.

### Key Components / Key Classes / Key Exports
- **`UsageTracker`**: Manages the SQLite database initialization and provides methods to securely log application usage events with fault-tolerant error handling.

### Integration Points
Interacts with the local SQLite database file path specified in initialization (defaulting to Sessions/usage_telemetry.db) and provides non-blocking logging hooks for application components.
