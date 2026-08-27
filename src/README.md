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

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
src/
├── backends/
│   ├── extensions/
│   ├── README.md
│   ├── __init__.py
│   ├── backend_ocolus.py
│   ├── backend_openxr.py
│   ├── backend_steamvr.py
│   ├── discovery.py
│   ├── openxr_headless.py
│   └── udp_receiver.py
├── central_server/
│   ├── admin_ui/
│   │   └── index.html
│   ├── README.md
│   ├── data_manager.py
│   ├── data_schema.py
│   └── server.py
├── core/
│   ├── README.md
│   ├── __init__.py
│   ├── datatypes.py
│   ├── engine.py
│   ├── exceptions.py
│   ├── interfaces.py
│   └── synchronizer.py
├── eye_tracking/
│   ├── README.md
│   ├── __init__.py
│   ├── base_driver.py
│   ├── ext_eye_gaze.py
│   ├── factory.py
│   ├── fb_social.py
│   └── htc_tracker.py
├── frontend/
│   └── VRTelemetry/
│       ├── public/
│       │   ├── favicon.svg
│       │   └── icons.svg
│       ├── src/
│       │   ├── assets/
│       │   │   ├── hero.png
│       │   │   ├── react.svg
│       │   │   └── vite.svg
│       │   ├── components/
│       │   │   ├── layout/
│       │   │   │   ├── AppShell.tsx
│       │   │   │   └── README.md
│       │   │   └── visualizations/
│       │   │       ├── README.md
│       │   │       └── SpatialViewer.tsx
│       │   ├── pages/
│       │   │   ├── Activation.tsx
│       │   │   ├── DataQuality.tsx
│       │   │   ├── Export.tsx
│       │   │   ├── EyeTracking.tsx
│       │   │   ├── Login.tsx
│       │   │   ├── Metadata.tsx
│       │   │   ├── NewSession.tsx
│       │   │   ├── Overview.tsx
│       │   │   ├── Physiology.tsx
│       │   │   ├── README.md
│       │   │   ├── RawDataExplorer.tsx
│       │   │   └── SessionExplorer.tsx
│       │   ├── services/
│       │   │   ├── README.md
│       │   │   └── TelemetryParser.ts
│       │   ├── store/
│       │   │   ├── README.md
│       │   │   └── useTelemetryStore.ts
│       │   ├── types/
│       │   │   ├── README.md
│       │   │   └── telemetry.ts
│       │   ├── App.css
│       │   ├── App.tsx
│       │   ├── README.md
│       │   ├── index.css
│       │   └── main.tsx
│       ├── README.md
│       ├── index.html
│       ├── package-lock.json
│       ├── package.json
│       ├── postcss.config.js
│       ├── tailwind.config.js
│       ├── tsconfig.app.json
│       ├── tsconfig.json
│       ├── tsconfig.node.json
│       └── vite.config.ts
├── license_service/
│   ├── README.md
│   ├── auth_manager.py
│   ├── bootstrap_admin.py
│   ├── db_schema.py
│   ├── local_cache.py
│   └── manager.py
├── storage/
│   ├── README.md
│   ├── __init__.py
│   ├── ai_preprocessor.py
│   ├── database_manager.py
│   ├── parquet_writer.py
│   ├── session_uploader.py
│   └── usage_tracker.py
├── utils/
│   ├── README.md
│   ├── __init__.py
│   ├── auto_installer.py
│   ├── hardware_monitor.py
│   ├── logger.py
│   └── system_profiler.py
├── README.md
├── main.py
├── server_entrypoint.py
└── tert_runner.py
```