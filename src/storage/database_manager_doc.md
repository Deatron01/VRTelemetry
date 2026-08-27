### Purpose
This module manages a relational SQLite database to store static experimental metadata, hardware configurations, calibration data, and subjective labels. It bridges high-frequency time-series datasets stored elsewhere by linking records using unique session UUIDs.

### Key Components / Key Classes / Key Exports
- **`DatabaseManager`**: Core class responsible for initializing the SQLite schema, opening database connections, and flattening nested metadata dictionaries for relational insertion.
- **`_initialize_schema`**: Internal method that creates the comprehensive `session_metadata` table covering categories like subject profiles, hardware specs, calibration, and system profiles.
- **`persist_experiment`**: Method that extracts category-specific sub-dictionaries from an experiment payload, maps them to SQL parameters, and handles insertion integrity.

### Integration Points
Interacts directly with the local file system using `pathlib` to create and locate the SQLite database file (`vr_metadata.db`). It consumes nested metadata dictionaries provided by upstream experiment execution or logging components and logs operational status using Python's standard `logging` library.
