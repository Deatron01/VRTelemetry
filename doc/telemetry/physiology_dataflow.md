```mermaid
graph TD
    A[useTelemetryStore] -->|Retrieves raw frames| B(Physiology Component)
    B -->|Downsamples & calculates speed| C[chartData Memo]
    C -->|Renders statistics| D[Summary Cards]
    C -->|Feeds dual-axis data| E[Recharts LineChart]
    E -->|Left Y-Axis| F[Heart Rate (BPM)]
    E -->|Right Y-Axis| G[Head Speed (m/s)]
```