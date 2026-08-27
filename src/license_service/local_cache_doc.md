### Purpose
The `local_cache.py` module manages local persistence for client installations using SQLite. It is responsible for caching license status, handling offline grace periods, tracking pending uploads that failed to reach the central server, and managing active user account sessions and generic app configurations.

### Key Components / Key Classes / Key Exports
- **`LocalLicenseCache`**: Main class that encapsulates SQLite operations for local machine data storage including license state, pending data uploads, user sessions, and local app configuration values.
- **`_init_schema`**: Initializes the SQLite database and establishes required tables (`license_state`, `pending_uploads`, `account_session`, `app_config`) if they do not exist.
- **`save` / `mark_revoked` / `is_valid_offline`**: Methods managing the local license lifecycle and verifying offline grace periods.
- **`queue_pending_upload` / `list_pending_uploads`**: Methods managing offline or failed session data synchronization queues.

### Integration Points
Interacts directly with the local file system to provision and read from a SQLite database file (typically located under `AppData/license_cache.db`). It serves as a standalone caching layer supporting client licensing checks and offline synchronization routines.
