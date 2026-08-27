### Purpose
This module serves as the primary entry point and unified FastAPI backend service for the VRTelemetry framework, combining a command-line interface pipeline with an extensive HTTP API. It orchestrates biometric data streaming sessions, hardware topology discovery, data synchronization, licensing validation, and remote storage capabilities.

### Key Components / Key Classes / Key Exports
- **`app`**: The central FastAPI web application instance providing endpoints for telemetry ingestion, session management, authentication, configuration, synchronization, and licensing.
- **`execute_pipeline()`**: Main CLI orchestration bootstrapper that validates GDPR consent, discovers hardware topology, and instantiates the telemetry background engine.
- **`upload_telemetry()`**: FastAPI endpoint that processes large Parquet tracking files via Pandas, performs downsampling for client rendering performance, and adjusts time-series timestamps.
- **`SessionStartConfig` / `SessionUpdate`**: Pydantic data models for validating incoming session initialization and modification payloads.

### Integration Points
Interfaces directly with the core `TelemetryEngine` for data acquisition, `RuntimeCapabilityDiscovery` for XR device detection, local SQLite databases (`vr_metadata.db`) for session storage, and an external central server for authentication, session synchronization, and license heartbeats.
