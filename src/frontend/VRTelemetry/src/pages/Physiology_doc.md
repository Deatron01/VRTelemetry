### Purpose
The Physiology component is a React page module that visualizes cross-modal VR telemetry data, specifically correlating user movement intensity with cardiovascular activity. It provides researchers with real-time statistical insights and synchronized time-series line charts comparing head velocity and heart rate.

### Key Components / Key Exports
- **`Physiology`**: The main React functional component responsible for rendering the dashboard UI, processing telemetry data frames via memoization, and displaying performance summary cards and charts.

### Integration Points
This module integrates directly with the global `useTelemetryStore` state hook to consume raw VR frame records, and leverages Recharts library components to render responsive, dual-axis multi-metric charts.
