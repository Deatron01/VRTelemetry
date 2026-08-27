# Telemetryparser Doc

### Purpose
This module parses and processes raw Virtual Reality (VR) telemetry files on the frontend before visualization. It uploads telemetry data to a backend server, extracts session metadata from filenames and stream data, and computes derived behavioral and physiological metrics.

### Key Components / Key Classes / Key Exports
- **`TelemetryParser`**: Primary static class responsible for handling file uploads, processing frame arrays, inferring hardware profiles, and calculating derived telemetry statistics.
- **`parseFile`**: Asynchronously submits a file to the backend telemetry processing endpoint and hands the response over to data processing routines.
- **`extractSubjectId`**: Performs heuristic parsing on filenames to extract standard subject IDs or session timestamps when database records are missing.
- **`inferHmdModel`**: Inspects eye-tracking and pupil characteristics within telemetry frames to heuristically classify the target head-mounted display.
- **`processData`**: Computes aggregated metrics such as head/hand kinematics, fixation ratios, heart rate averages, pupil diameters, and peak saccades.

### Integration Points
Interfaces directly with the backend server via HTTP POST requests (`http://localhost:8000/api/upload-telemetry`) to parse raw files, and consumes shared TypeScript types (`TelemetryFrame`, `SessionMetadata`, `DerivedMetrics`) from the frontend telemetry type definitions.

---
