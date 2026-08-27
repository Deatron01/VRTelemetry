```mermaid
graph TD
    HW[Hardware Inputs: HMD, Controllers, Eye Tracker, Sensors] -->|Raw Data| TF[TelemetryFrame dataclass]
    TF -->|to_tuple()| PA[PyArrow Memory Tables]
    Drop[Hardware Drop / Lag] -->|create_empty()| TF
```