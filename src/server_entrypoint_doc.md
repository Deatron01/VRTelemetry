### Purpose
This module serves as the desktop-app entry point for the backend server, initializing logging and booting the FastAPI server via Uvicorn. It allows the Electron-hosted frontend to communicate with the application over HTTP.

### Key Components / Key Classes / Key Exports
- **`boot_server_context`**: Initializes global application logging and starts the Uvicorn ASGI server hosting the FastAPI application on local port 8000.

### Integration Points
Interacts with `src.utils.logger` to setup logging configurations, `src.main` to retrieve the FastAPI application instance, and launches a local HTTP server using `uvicorn` for the frontend client.
