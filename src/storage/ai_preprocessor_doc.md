### Purpose
This module acts as an offline data refinement pipeline designed to transform raw nanosecond time-series matrices into standardized, normalized tensors. It fulfills Requirement Category 8 (Adatfeldolgozási Metaadat) by preparing high-frequency numerical data for downstream deep learning models like multi-layer perceptrons or recurrent neural networks.

### Key Components / Key Classes / Key Exports
- **`AIPostProcessor`**: Manages the ingestion of raw parquet files, execution of preprocessing filters, feature engineering steps such as exponential moving average smoothing and Z-score standardization, and writing out tensor-ready datasets.

### Integration Points
Interacts directly with the local file system using the `pathlib` library to read raw Apache Parquet files and write out processed `_ai_ready.parquet` datasets, leveraging `pandas`, `numpy`, and `pyarrow` for memory-efficient data manipulation and schema handling.
