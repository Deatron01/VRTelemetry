### Purpose
This module implements the core FastAPI server application for the VRTelemetry Central Hub, exposing public authentication, desktop license validation, and telemetry data upload endpoints, alongside fully protected administrative management endpoints.

### Key Components / Key Classes / Key Exports
- **`app`**: The primary FastAPI application instance containing all API routes and mounting the static admin UI.
- **`require_admin`**: FastAPI dependency that verifies session tokens and ensures the caller holds administrative privileges.
- **`activate_license` / `heartbeat`**: Client-facing endpoints for verifying and maintaining software license state.
- **`upload_session` / `upload_session_log`**: Endpoints accepting telemetry data packages and log files from authorized active machines.

### Integration Points
Interacts directly with `LicenseManager`, `AuthManager`, and `CentralDataManager` services to manage application data, user authentication, and licensing workflows. It also interfaces with local disk storage for hosting the admin UI static files and handling uploaded session assets.
