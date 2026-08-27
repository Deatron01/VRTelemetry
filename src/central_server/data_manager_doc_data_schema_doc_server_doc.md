# Data Manager Doc

### Purpose
This module manages the secure ingestion, storage, and database persistence of experimental session data and logs received from researcher machines. It acts as the central repository data handler, implementing idempotency checks, SHA-256 integrity verification, and structured event logging for auditing uploads.

### Key Components / Key Classes / Key Exports
- **`CentralDataManager`**: Main class responsible for handling file uploads, storing binaries on disk namespaced by license, tracking metadata, and managing SQLite database records for sessions and logs.
- **`ingest_session`**: Core intake routine that validates checksums, prevents unauthorized overwrites through conflict detection, verifies storage integrity, and records upload metadata and events.
- **`ingest_log`**: Handles the storage and database upsert operations for supplementary session log files.
- **`list_sessions` / `get_file_path` / `get_log_path`**: Query utilities to retrieve session records and resolve absolute storage paths for stored payloads.

### Integration Points
This module integrates directly with an SQLite database for transactional provenance tracking and utilizes the local filesystem for namespaced binary and log file storage. It is typically invoked by FastAPI route handlers on the central server after upstream authentication and license validation have been established.

---

# Data Schema Doc

### Purpose
This module manages the core relational database schema for the central server using SQLite. It is responsible for setting up tracking tables for uploaded researcher sessions, upload events, and session logs, ensuring provenance and data integrity.

### Key Components / Key Classes / Key Exports
- **`initialize_data_schema`**: Ensures parent directories exist for the database path, executes the complete database schema script including tables and indexes, and handles transaction commits and error logging.

### Integration Points
It interfaces directly with the local file system to construct database directories and connects to SQLite database files specified via the `db_path` parameter, serving as the foundational storage setup for the central server application.

---

# Server Doc

### Purpose
This module implements the core FastAPI server application for the VRTelemetry Central Hub, exposing public authentication, desktop license validation, and telemetry data upload endpoints, alongside fully protected administrative management endpoints.

### Key Components / Key Classes / Key Exports
- **`app`**: The primary FastAPI application instance containing all API routes and mounting the static admin UI.
- **`require_admin`**: FastAPI dependency that verifies session tokens and ensures the caller holds administrative privileges.
- **`activate_license` / `heartbeat`**: Client-facing endpoints for verifying and maintaining software license state.
- **`upload_session` / `upload_session_log`**: Endpoints accepting telemetry data packages and log files from authorized active machines.

### Integration Points
Interacts directly with `LicenseManager`, `AuthManager`, and `CentralDataManager` services to manage application data, user authentication, and licensing workflows. It also interfaces with local disk storage for hosting the admin UI static files and handling uploaded session assets.

---
