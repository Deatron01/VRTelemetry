flowchart TD
    Raw[Raw Parquet Input<br/>vr_telemetry_TIMESTAMP.parquet] --> Read[Read as PyArrow Table / Pandas DataFrame]
    
    Read --> V1{Check for Sensor Dropouts<br/>(e.g., Blinking)}
    V1 -- Missing Data --> FF[Forward-Fill (ffill)<br/>Preserve Last Known Vector]
    V1 -- No Missing Data --> M2
    FF --> M2
    
    M2[Temporal Smoothing Pipeline] --> EMA_Eye[Apply Exponential Moving Average<br/>(EMA) to Eye Gaze Vectors]
    EMA_Eye --> EMA_Kin[Apply EMA to High-Frequency<br/>HMD Kinematics]
    
    EMA_Kin --> ZScore[Z-Score Standardization<br/>(Normalize 0 Mean, 1 Variance)]
    
    ZScore --> Output[Export AI-Ready Parquet<br/>vr_telemetry_TIMESTAMP_ai_ready.parquet]
    
    Output -.-> Model[PyTorch DataLoader / DL Model]

    classDef process fill:#e1bee7,stroke:#8e24aa,stroke-width:2px,color:#000;
    classDef io fill:#bbdefb,stroke:#2196f3,stroke-width:2px,color:#000;
    
    class Raw,Output,Model io;
    class FF,EMA_Eye,EMA_Kin,ZScore process;