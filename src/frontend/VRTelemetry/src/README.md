# App Doc Main Doc

# App Doc

### Purpose
App.tsx serves as the root React component and application controller for the VRTelemetry frontend. It manages top-level authentication states, license validation flows, application routing, and layout shells for the entire telemetry suite.

### Key Components / Key Classes / Key Exports
- **`App`**: Main functional component maintaining state for active routes, authenticated users, and license statuses, rendering corresponding pages conditionally.
- **`AuthedUser`**: Interface defining user profile structure including email and display name.
- **`LicenseState`**: Type definition representing the status of software licensing ('checking', 'active', 'inactive').

### Integration Points
Interacts directly with the backend API endpoints running on localhost:8000 for session validation, authentication checks, and license verification. It renders various domain-specific pages such as EyeTracking, Physiology, SpatialViewer, and SessionExplorer within an AppShell layout wrapper.

---

# Main Doc

### Purpose
This module serves as the primary entry point for the React application. It bootstraps the entire frontend by mounting the root App component into the DOM element with the ID 'root'.

### Key Components / Key Classes / Key Exports
- **`ReactDOM.createRoot`**: Initializes the React 18 concurrent root on the target DOM node.
- **`App`**: The root React component containing the main application layout and routing.
- **`React.StrictMode`**: A wrapper component used for highlighting potential problems in the application during development.

### Integration Points
This module integrates directly with the HTML DOM via the `document.getElementById('root')` selector and imports global styles from `index.css` alongside the root component `App.tsx`.

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
src/
├── assets/
│   ├── hero.png
│   ├── react.svg
│   └── vite.svg
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx
│   │   └── README.md
│   └── visualizations/
│       ├── README.md
│       └── SpatialViewer.tsx
├── pages/
│   ├── Activation.tsx
│   ├── DataQuality.tsx
│   ├── Export.tsx
│   ├── EyeTracking.tsx
│   ├── Login.tsx
│   ├── Metadata.tsx
│   ├── NewSession.tsx
│   ├── Overview.tsx
│   ├── Physiology.tsx
│   ├── README.md
│   ├── RawDataExplorer.tsx
│   └── SessionExplorer.tsx
├── services/
│   ├── README.md
│   └── TelemetryParser.ts
├── store/
│   ├── README.md
│   └── useTelemetryStore.ts
├── types/
│   ├── README.md
│   └── telemetry.ts
├── App.css
├── App.tsx
├── README.md
├── index.css
└── main.tsx
```