### Purpose
The `DataQuality` component serves as a telemetry quality assurance dashboard page within the VRTelemetry frontend application. It calculates and visualizes key signal integrity metrics, sampling stability, jitter, and dropout events to help researchers evaluate data reliability.

### Key Components / Key Classes / Key Exports
- **`DataQuality`**: React functional component that renders the quality assurance dashboard layout and metric cards.
- **`qualityStats` (useMemo)**: Computes signal metrics including HMD and eye tracking dropouts, average and maximum jitter in milliseconds, data completeness percentage, and a weighted overall quality score.

### Integration Points
Interacts with the global `useTelemetryStore` state management hook to retrieve loaded telemetry frames and dataset metadata for real-time calculations.
