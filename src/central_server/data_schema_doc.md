### Purpose
This module manages the core relational database schema for the central server using SQLite. It is responsible for setting up tracking tables for uploaded researcher sessions, upload events, and session logs, ensuring provenance and data integrity.

### Key Components / Key Classes / Key Exports
- **`initialize_data_schema`**: Ensures parent directories exist for the database path, executes the complete database schema script including tables and indexes, and handles transaction commits and error logging.

### Integration Points
It interfaces directly with the local file system to construct database directories and connects to SQLite database files specified via the `db_path` parameter, serving as the foundational storage setup for the central server application.
