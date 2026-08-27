# Main Doc Server Entrypoint Doc Tert Runner Doc

# Main Doc

### Purpose
This module serves as the primary entry point and unified FastAPI backend service for the VRTelemetry framework, combining a command-line interface pipeline with an extensive HTTP API. It orchestrates biometric data streaming sessions, hardware topology discovery, data synchronization, licensing validation, and remote storage capabilities.

### Key Components / Key Classes / Key Exports
- **`app`**: The central FastAPI web application instance providing endpoints for telemetry ingestion, session management, authentication, configuration, synchronization, and licensing.
- **`execute_pipeline()`**: Main CLI orchestration bootstrapper that validates GDPR consent, discovers hardware topology, and instantiates the telemetry background engine.
- **`upload_telemetry()`**: FastAPI endpoint that processes large Parquet tracking files via Pandas, performs downsampling for client rendering performance, and adjusts time-series timestamps.
- **`SessionStartConfig` / `SessionUpdate`**: Pydantic data models for validating incoming session initialization and modification payloads.

### Integration Points
Interfaces directly with the core `TelemetryEngine` for data acquisition, `RuntimeCapabilityDiscovery` for XR device detection, local SQLite databases (`vr_metadata.db`) for session storage, and an external central server for authentication, session synchronization, and license heartbeats.

---

# Server Entrypoint Doc

### Purpose
This module serves as the desktop-app entry point for the backend server, initializing logging and booting the FastAPI server via Uvicorn. It allows the Electron-hosted frontend to communicate with the application over HTTP.

### Key Components / Key Classes / Key Exports
- **`boot_server_context`**: Initializes global application logging and starts the Uvicorn ASGI server hosting the FastAPI application on local port 8000.

### Integration Points
Interacts with `src.utils.logger` to setup logging configurations, `src.main` to retrieve the FastAPI application instance, and launches a local HTTP server using `uvicorn` for the frontend client.

---

# Tert Runner Doc

### Purpose
This module serves as the primary administrative initialization entry point for the application. It validates package alignment, configures active logging mechanisms, verifies dependencies, and hands off execution control to the main pipeline.

### Key Components / Key Classes / Key Exports
- **`boot_framework_context`**: Initializes logging, triggers automatic dependency verification, logs bootstrapping status, and invokes the main execution pipeline.

### Integration Points
This module interfaces directly with `verify_and_install_dependencies` for environment checks, `setup_logging` and `logger` for telemetry, and `execute_pipeline` from the main package to drive core application behavior.

---

---
