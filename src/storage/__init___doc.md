### Purpose
The `storage` module serves as the persistence layer for the telemetry framework. It provides robust mechanisms for asynchronously writing binary matrix data using Parquet and managing relational metadata via SQLite.

### Key Components / Key Classes / Key Exports
- **`AsyncParquetWriter`**: Asynchronously flushes and writes binary matrix and telemetry data to Parquet files for efficient long-term storage.
- **`DatabaseManager`**: Handles relational metadata storage, schema migrations, and queries using SQLite.

### Integration Points
This module integrates directly with the telemetry data generation pipelines to persist telemetry metrics and matrix outputs, bridging runtime data collection with persistent disk storage.
