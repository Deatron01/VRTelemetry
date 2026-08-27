### Purpose
This module manages the secure ingestion, storage, and database persistence of experimental session data and logs received from researcher machines. It acts as the central repository data handler, implementing idempotency checks, SHA-256 integrity verification, and structured event logging for auditing uploads.

### Key Components / Key Classes / Key Exports
- **`CentralDataManager`**: Main class responsible for handling file uploads, storing binaries on disk namespaced by license, tracking metadata, and managing SQLite database records for sessions and logs.
- **`ingest_session`**: Core intake routine that validates checksums, prevents unauthorized overwrites through conflict detection, verifies storage integrity, and records upload metadata and events.
- **`ingest_log`**: Handles the storage and database upsert operations for supplementary session log files.
- **`list_sessions` / `get_file_path` / `get_log_path`**: Query utilities to retrieve session records and resolve absolute storage paths for stored payloads.

### Integration Points
This module integrates directly with an SQLite database for transactional provenance tracking and utilizes the local filesystem for namespaced binary and log file storage. It is typically invoked by FastAPI route handlers on the central server after upstream authentication and license validation have been established.
