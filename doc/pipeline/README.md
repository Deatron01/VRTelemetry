# Ai Post Processor Flow Ai Preprocessor Pipeline Tert Runner Pipeline Udp Receiver Pipeline

# Ai Post Processor Flow

```mermaid
flowchart TD
    Raw["Raw Parquet Input<br/>vr_telemetry_TIMESTAMP.parquet"] --> Read["Read as PyArrow Table / Pandas DataFrame"]
    Read --> V1{"Check for Sensor Dropouts<br/>(e.g., Blinking)"}
    V1 -- Missing Data --> FF["Forward-Fill (ffill)<br/>Preserve Last Known Vector"]
    V1 -- No Missing Data --> M2
    FF --> M2
    M2["Temporal Smoothing Pipeline"] --> EMA_Eye["Apply Exponential Moving Average<br/>(EMA) to Eye Gaze Vectors"]
    EMA_Eye --> EMA_Kin["Apply EMA to High-Frequency<br/>HMD Kinematics"]
    EMA_Kin --> ZScore["Z-Score Standardization<br/>(Normalize 0 Mean, 1 Variance)"]
    ZScore --> Output["Export AI-Ready Parquet<br/>vr_telemetry_TIMESTAMP_ai_ready.parquet"]
    Output -.-> Model["PyTorch DataLoader / DL Model"]
    classDef process fill:#e1bee7,stroke:#8e24aa,stroke-width:2px,color:#000;
    classDef io fill:#bbdefb,stroke:#2196f3,stroke-width:2px,color:#000;
    class Raw,Output,Model io;
    class FF,EMA_Eye,EMA_Kin,ZScore process;
```

---

# Ai Preprocessor Pipeline

```mermaid
graph TD
    A[Raw Parquet File] -->|pq.read_table| B(AIPostProcessor)
    B --> C{Missing Values?}
    C -->|Yes| D[Forward Fill & Zero Fallback]
    C -->|No| E[EMA Smoothing on Pos Columns]
    D --> E
    E --> F[Z-Score Standardization]
    F --> G[PyArrow Schema Mutation]
    G --> H[Tensor-Ready Output Parquet]
```

---

# Tert Runner Pipeline

```mermaid
flowchart TD
    A[Start: __main__] --> B[boot_framework_context]
    B --> C[setup_logging]
    C --> D[verify_and_install_dependencies]
    D --> E[Log Bootstrap Complete]
    E --> F[execute_pipeline]
    F --> G[End]
```

---

# Udp Receiver Pipeline

```mermaid
pipeline
    title UDP Ingestion Pipeline
    subgraph Source
        A[Quest Pro Overlay] -->|Raw UDP Datagrams| B(NativeQuestHarvesterProtocol)
    end
    subgraph Ingestion Service
        B --> C{Packet Size Valid?}
        C -->|No| D[Discard Packet]
        C -->|Yes| E[Unpack 64-byte Binary Struct]
        E --> F[Map to TelemetryFrame]
        F --> G[Normalize Confidences]
        G --> H[Push to BiometricSynchronizer]
    end
```

---

---
