#   Init   Doc

### Purpose
The `storage` module serves as the persistence layer for the telemetry framework. It provides robust mechanisms for asynchronously writing binary matrix data using Parquet and managing relational metadata via SQLite.

### Key Components / Key Classes / Key Exports
- **`AsyncParquetWriter`**: Asynchronously flushes and writes binary matrix and telemetry data to Parquet files for efficient long-term storage.
- **`DatabaseManager`**: Handles relational metadata storage, schema migrations, and queries using SQLite.

### Integration Points
This module integrates directly with the telemetry data generation pipelines to persist telemetry metrics and matrix outputs, bridging runtime data collection with persistent disk storage.

---

# Ai Preprocessor Doc

### Purpose
This module acts as an offline data refinement pipeline designed to transform raw nanosecond time-series matrices into standardized, normalized tensors. It fulfills Requirement Category 8 (Adatfeldolgozási Metaadat) by preparing high-frequency numerical data for downstream deep learning models like multi-layer perceptrons or recurrent neural networks.

### Key Components / Key Classes / Key Exports
- **`AIPostProcessor`**: Manages the ingestion of raw parquet files, execution of preprocessing filters, feature engineering steps such as exponential moving average smoothing and Z-score standardization, and writing out tensor-ready datasets.

### Integration Points
Interacts directly with the local file system using the `pathlib` library to read raw Apache Parquet files and write out processed `_ai_ready.parquet` datasets, leveraging `pandas`, `numpy`, and `pyarrow` for memory-efficient data manipulation and schema handling.

---

# Database Manager Doc

### Purpose
This module manages a relational SQLite database to store static experimental metadata, hardware configurations, calibration data, and subjective labels. It bridges high-frequency time-series datasets stored elsewhere by linking records using unique session UUIDs.

### Key Components / Key Classes / Key Exports
- **`DatabaseManager`**: Core class responsible for initializing the SQLite schema, opening database connections, and flattening nested metadata dictionaries for relational insertion.
- **`_initialize_schema`**: Internal method that creates the comprehensive `session_metadata` table covering categories like subject profiles, hardware specs, calibration, and system profiles.
- **`persist_experiment`**: Method that extracts category-specific sub-dictionaries from an experiment payload, maps them to SQL parameters, and handles insertion integrity.

### Integration Points
Interacts directly with the local file system using `pathlib` to create and locate the SQLite database file (`vr_metadata.db`). It consumes nested metadata dictionaries provided by upstream experiment execution or logging components and logs operational status using Python's standard `logging` library.

---

# Parquet Writer Doc

### Purpose
This module provides high-throughput columnar data storage by buffering telemetry vectors in memory and flushing them asynchronously as Apache Parquet files. It prevents blocking high-frequency hardware acquisition loops while ensuring strict Float32 compliance optimized for downstream AI model ingestion.

### Key Components / Key Classes / Key Exports
- **`AsyncParquetWriter`**: Manages buffered telemetry data, implements a defined PyArrow schema for 32-bit floating point data, and handles thread-safe asynchronous disk flushing and stream lifecycle management.
- **`_define_schema`**: Establishes the exact memory layout and column definitions matching specifications for HMD kinematics, controllers, eye tracking, biometrics, and virtual environment state.

### Integration Points
Interfaces directly with high-frequency hardware acquisition loops and synchronizer queues via the `push()` method. It utilizes the `pyarrow` and `pyparquet` libraries to write compressed columnar output to the local file system.

---

# Session Uploader Doc

### Purpose
The `session_uploader` module handles transmitting completed recording sessions and associated logs to a central hub server. It integrates local licensing state checks and robust failure handling, ensuring failed uploads are queued locally for automatic or on-demand retries.

### Key Components / Key Classes / Key Exports
- **`SessionUploader`**: Core class responsible for executing HTTP POST requests to upload session parquet files and log files, managing local retry queues, and verifying active licenses before transmission.
- **`upload`**: Sends session data and metadata to the central server, queuing the item locally upon network failure or invalid license states.
- **`retry_pending`**: Sweeps the local pending-uploads queue to re-attempt transmission of previously failed sessions.
- **`upload_log`**: Uploads secondary session logs to a dedicated endpoint on the central server.

### Integration Points
This module integrates directly with the `LocalLicenseCache` to fetch authorization states, manage failed upload queues, and clear records upon successful syncs. It uses the `requests` library to communicate with the central server endpoints and interacts with the filesystem via `pathlib.Path` to read local Parquet and log files.

---

# Usage Tracker Doc

### Purpose
This module tracks application-level telemetry such as page views, session start and stop actions, and export usage. It is intentionally kept separate from biometric session metadata to adhere to distinct consent scopes and application lifecycles.

### Key Components / Key Classes / Key Exports
- **`UsageTracker`**: Manages the SQLite database initialization and provides methods to securely log application usage events with fault-tolerant error handling.

### Integration Points
Interacts with the local SQLite database file path specified in initialization (defaulting to Sessions/usage_telemetry.db) and provides non-blocking logging hooks for application components.

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
storage/
├── README.md
├── __init__.py
├── ai_preprocessor.py
├── database_manager.py
├── parquet_writer.py
├── session_uploader.py
└── usage_tracker.py
```