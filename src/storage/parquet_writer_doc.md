### Purpose
This module provides high-throughput columnar data storage by buffering telemetry vectors in memory and flushing them asynchronously as Apache Parquet files. It prevents blocking high-frequency hardware acquisition loops while ensuring strict Float32 compliance optimized for downstream AI model ingestion.

### Key Components / Key Classes / Key Exports
- **`AsyncParquetWriter`**: Manages buffered telemetry data, implements a defined PyArrow schema for 32-bit floating point data, and handles thread-safe asynchronous disk flushing and stream lifecycle management.
- **`_define_schema`**: Establishes the exact memory layout and column definitions matching specifications for HMD kinematics, controllers, eye tracking, biometrics, and virtual environment state.

### Integration Points
Interfaces directly with high-frequency hardware acquisition loops and synchronizer queues via the `push()` method. It utilizes the `pyarrow` and `pyparquet` libraries to write compressed columnar output to the local file system.
