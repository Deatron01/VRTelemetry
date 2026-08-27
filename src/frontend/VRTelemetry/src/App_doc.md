### Purpose
App.tsx serves as the root React component and application controller for the VRTelemetry frontend. It manages top-level authentication states, license validation flows, application routing, and layout shells for the entire telemetry suite.

### Key Components / Key Classes / Key Exports
- **`App`**: Main functional component maintaining state for active routes, authenticated users, and license statuses, rendering corresponding pages conditionally.
- **`AuthedUser`**: Interface defining user profile structure including email and display name.
- **`LicenseState`**: Type definition representing the status of software licensing ('checking', 'active', 'inactive').

### Integration Points
Interacts directly with the backend API endpoints running on localhost:8000 for session validation, authentication checks, and license verification. It renders various domain-specific pages such as EyeTracking, Physiology, SpatialViewer, and SessionExplorer within an AppShell layout wrapper.
