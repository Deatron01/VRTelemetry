# Appshell Doc

### Purpose
AppShell serves as the main layout container and application frame for the VRTelemetry Research Studio. It orchestrates top-level navigation, file ingestion of telemetry sessions, and a real-time playback controller for multi-modal biometric and spatial data analysis.

### Key Components / Key Classes / Key Exports
- **`AppShell`**: React functional component that renders the top header, sidebar navigation, dynamic main content area, and playback footer controls.
- **`animate`**: Animation frame loop function that downsamples high-frequency (2000Hz) telemetry frame arrays to a synced 60Hz visual render using requestAnimationFrame.
- **`handleFileUpload`**: Event handler that triggers parquet file parsing via TelemetryParser and initializes the global telemetry store.

### Integration Points
Interacts directly with `useTelemetryStore` for global state management (frames, current frame index, playback states, speeds), `TelemetryParser` for asynchronous parsing of uploaded `.parquet` data files, and Lucide React icons for UI iconography.

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
layout/
├── AppShell.tsx
└── README.md
```