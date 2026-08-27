### Purpose
The `NewSession` React component acts as the live acquisition control panel for VR telemetry data collection. It enables researchers to configure session parameters, choose runtime tracking backends, enforce explicit GDPR compliance, and safely start or stop hardware recording sessions.

### Key Components / Key Classes / Key Exports
- **`NewSession`**: The primary functional React component rendering the configuration forms, operational status monitors, and lifecycle trigger buttons.
- **`handleStart`**: Asynchronous function that validates GDPR consent and initiates the telemetry recording pipeline via a POST request to the backend.
- **`handleStop`**: Asynchronous function that terminates the ongoing acquisition session and signals backend buffer sealing.

### Integration Points
This component integrates directly with backend API endpoints (`http://localhost:8000/api/recording/start` and `http://localhost:8000/api/recording/stop`) to control local VR hardware drivers, stream configurations, and remote central server synchronization targets.
