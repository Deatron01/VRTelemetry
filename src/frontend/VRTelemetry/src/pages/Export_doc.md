### Purpose
This module provides a React frontend component (`Export`) allowing researchers to export loaded VR telemetry data into multiple formats (CSV, JSON, and printable HTML/PDF reports) and sync offline sessions back to a central server.

### Key Components / Key Classes / Key Exports
- **`Export`**: The main React functional component responsible for rendering the export dashboard, managing export/sync states, and triggering client-side file downloads.
- **`downloadBlob`**: A helper function that creates a temporary object URL from a Blob and simulates an anchor click to trigger browser file downloads.

### Integration Points
Interacts with `useTelemetryStore` to access active session metadata, calculated metrics, and frame-level telemetry rows. It also communicates with local backend endpoints (`http://localhost:8000/api/sync/status` and `http://localhost:8000/api/sync/retry`) to fetch and execute data synchronization tasks.
