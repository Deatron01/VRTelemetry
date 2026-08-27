### Purpose
This module defines the TypeScript data structures and interfaces used across the frontend VRTelemetry application to represent recorded session data, frame-by-frame telemetry feeds, and derived performance metrics. It acts as the foundational contract for parsing, analyzing, and visualizing virtual reality telemetry streams.

### Key Components / Key Classes / Key Exports
- **`TelemetryFrame`**: Defines the raw spatial, ocular, and physiological data captured per frame, including headset and eye tracking positions, validity flags, and optional controller properties.
- **`SessionMetadata`**: Captures high-level properties of a recorded session such as duration, sampling rate, validity percentages, and optional subjective survey scores.
- **`DerivedMetrics`**: Represents aggregated and processed statistics computed from raw telemetry frames, such as focus ratio, head speed, and mean pupil diameter.

### Integration Points
This module integrates directly with the telemetry parser services, frontend visualization components, and overview dashboards that consume typed structures to render graphs, statistical summaries, and session analytics.
