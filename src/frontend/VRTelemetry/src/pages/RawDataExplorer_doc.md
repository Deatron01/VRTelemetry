### Purpose
RawDataExplorer is a diagnostic React component that provides a tabular view of low-level VR telemetry frames. It allows developers and researchers to directly inspect raw frame data, including head-mounted display (HMD) coordinates, tracking validity flags, and physiological metrics like heart rate.

### Key Components / Key Exports
- **`RawDataExplorer`**: The primary React functional component rendering a paginated, scrollable data table using TanStack Table.

### Integration Points
This component consumes telemetry frames from the global state store via `useTelemetryStore` and relies on `@tanstack/react-table` for core table management, pagination, and data rendering.
