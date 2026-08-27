### Purpose
The EyeTracking module is a React functional component that renders a laboratory interface for analyzing VR user eye-tracking telemetry. It processes raw frame data to calculate metrics such as binocular validity, mean gaze activity, and peak saccade intensity, displaying them via summary cards and a responsive area chart.

### Key Components / Key Classes / Key Exports
- **`EyeTracking`**: The primary React export that consumes the telemetry store, computes scaled quaternion-based angular velocities, and renders visualization charts.
- **`chartData` (useMemo)**: Downsamples and transforms telemetry frames into time-series data representing gaze shifts or saccadic activity.

### Integration Points
This module integrates directly with `useTelemetryStore` to subscribe to incoming VR frame logs and utilizes components from the `recharts` library for rendering visual telemetry analytics.
