### Purpose
The Metadata component serves as a diagnostic dashboard view for VR telemetry sessions, rendering file statistics, hardware detection states, and extracted parquet schema definitions. It provides researchers with immediate visibility into session integrity and available sensor channels.

### Key Components / Key Classes / Key Exports
- **`Metadata`**: React functional component that reads telemetry metadata and frame lists from the global state store to display file details, sensor availability, and schema columns.

### Integration Points
Interacts directly with the `useTelemetryStore` Zustand store to retrieve session `metadata` and telemetry `frames` arrays.
