```mermaid
graph TD
    A[useTelemetryStore] -->|frames array| B(EyeTracking Component)
    B -->|useMemo calculation| C[chartData array]
    C -->|renders metrics| D[Metric Summary Cards]
    C -->|renders chart| E[ResponsiveContainer AreaChart]
```
