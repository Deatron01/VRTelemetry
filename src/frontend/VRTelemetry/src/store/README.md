# Usetelemetrystore Doc

### Purpose
This module provides a centralized state management store built with Zustand for handling Virtual Reality (VR) telemetry data within the frontend application. It manages session frames, metadata, derived metrics, and playback states like current frame index, play/pause status, playback speed, and active time selection ranges.

### Key Components / Key Classes / Key Exports
- **`useTelemetryStore`**: The main Zustand hook exporting both telemetry state properties and action functions.
- **`loadSession`**: Action to initialize the store with new telemetry frames, session metadata, and metrics, while resetting the playback index and time range.
- **`setFrameIdx`**: Updates the currently active telemetry frame index.
- **`togglePlayback`**: Toggles the active playing state of the session.
- **`setPlaybackSpeed`**: Modifies the speed multiplier for telemetry playback.
- **`setTimeRange`**: Sets the active start and end index bounds for data visualization and playback.

### Integration Points
This store is consumed directly by React components in the VR telemetry frontend to render live or recorded session data, control playback timelines, and synchronize UI state with underlying metrics.

---
