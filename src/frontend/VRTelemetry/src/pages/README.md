# Activation Doc Dataquality Doc Export Doc Eyetracking Doc Login Doc Metadata Doc Newsession Doc Overview Doc Physiology Doc Rawdataexplorer Doc Sessionexplorer Doc

# Activation Doc

### Purpose
This module provides the Activation page component for the VRTelemetry frontend, enabling users to register un-licensed machines using an administrative license key. It renders a clean, modern form interface to securely transmit license credentials to the backend API and update the application lifecycle state upon success.

### Key Components / Key Classes / Key Exports
- **`Activation`**: A React functional component that manages local form state, handles user input validation, invokes the remote activation endpoint, and renders error alerts or loading indicators.
- **`ActivationProps`**: Interface defining the component contract, specifically exposing the `onActivated` callback triggered upon successful license verification.

### Integration Points
Interacts directly with the backend REST API via a `POST` request to `http://localhost:8000/api/license/activate` passing the user-supplied license key. It invokes the parent-provided `onActivated` callback to transition the application state when activation succeeds.

---

# Dataquality Doc

### Purpose
The `DataQuality` component serves as a telemetry quality assurance dashboard page within the VRTelemetry frontend application. It calculates and visualizes key signal integrity metrics, sampling stability, jitter, and dropout events to help researchers evaluate data reliability.

### Key Components / Key Classes / Key Exports
- **`DataQuality`**: React functional component that renders the quality assurance dashboard layout and metric cards.
- **`qualityStats` (useMemo)**: Computes signal metrics including HMD and eye tracking dropouts, average and maximum jitter in milliseconds, data completeness percentage, and a weighted overall quality score.

### Integration Points
Interacts with the global `useTelemetryStore` state management hook to retrieve loaded telemetry frames and dataset metadata for real-time calculations.

---

# Export Doc

### Purpose
This module provides a React frontend component (`Export`) allowing researchers to export loaded VR telemetry data into multiple formats (CSV, JSON, and printable HTML/PDF reports) and sync offline sessions back to a central server.

### Key Components / Key Classes / Key Exports
- **`Export`**: The main React functional component responsible for rendering the export dashboard, managing export/sync states, and triggering client-side file downloads.
- **`downloadBlob`**: A helper function that creates a temporary object URL from a Blob and simulates an anchor click to trigger browser file downloads.

### Integration Points
Interacts with `useTelemetryStore` to access active session metadata, calculated metrics, and frame-level telemetry rows. It also communicates with local backend endpoints (`http://localhost:8000/api/sync/status` and `http://localhost:8000/api/sync/retry`) to fetch and execute data synchronization tasks.

---

# Eyetracking Doc

### Purpose
The EyeTracking module is a React functional component that renders a laboratory interface for analyzing VR user eye-tracking telemetry. It processes raw frame data to calculate metrics such as binocular validity, mean gaze activity, and peak saccade intensity, displaying them via summary cards and a responsive area chart.

### Key Components / Key Classes / Key Exports
- **`EyeTracking`**: The primary React export that consumes the telemetry store, computes scaled quaternion-based angular velocities, and renders visualization charts.
- **`chartData` (useMemo)**: Downsamples and transforms telemetry frames into time-series data representing gaze shifts or saccadic activity.

### Integration Points
This module integrates directly with `useTelemetryStore` to subscribe to incoming VR frame logs and utilizes components from the `recharts` library for rendering visual telemetry analytics.

---

# Login Doc

### Purpose
This module provides the authentication and user registration interface for the VRTelemetry Research Studio application. It allows researchers to sign into their accounts or register new organization labs to access telemetry workspaces.

### Key Components / Key Classes / Key Exports
- **`Login`**: React functional component that renders the authentication form, manages internal form state, handles switching between login and registration modes, and processes network authentication requests.

### Integration Points
Interacts with backend authentication endpoints (`/api/auth/login` and `/api/auth/register`) via HTTP POST requests and invokes the `onAuthenticated` callback prop upon successful user sign-in to propagate session data.

---

# Metadata Doc

### Purpose
The Metadata component serves as a diagnostic dashboard view for VR telemetry sessions, rendering file statistics, hardware detection states, and extracted parquet schema definitions. It provides researchers with immediate visibility into session integrity and available sensor channels.

### Key Components / Key Classes / Key Exports
- **`Metadata`**: React functional component that reads telemetry metadata and frame lists from the global state store to display file details, sensor availability, and schema columns.

### Integration Points
Interacts directly with the `useTelemetryStore` Zustand store to retrieve session `metadata` and telemetry `frames` arrays.

---

# Newsession Doc

### Purpose
The `NewSession` React component acts as the live acquisition control panel for VR telemetry data collection. It enables researchers to configure session parameters, choose runtime tracking backends, enforce explicit GDPR compliance, and safely start or stop hardware recording sessions.

### Key Components / Key Classes / Key Exports
- **`NewSession`**: The primary functional React component rendering the configuration forms, operational status monitors, and lifecycle trigger buttons.
- **`handleStart`**: Asynchronous function that validates GDPR consent and initiates the telemetry recording pipeline via a POST request to the backend.
- **`handleStop`**: Asynchronous function that terminates the ongoing acquisition session and signals backend buffer sealing.

### Integration Points
This component integrates directly with backend API endpoints (`http://localhost:8000/api/recording/start` and `http://localhost:8000/api/recording/stop`) to control local VR hardware drivers, stream configurations, and remote central server synchronization targets.

---

# Overview Doc

### Purpose
The `Overview` component serves as a primary diagnostic dashboard for VR telemetry data, displaying high-fidelity biophysical snapshots and experimental metadata. It aggregates spatial-temporal acquisition parameters, clinical apparatus context, and psychophysical or kinematic analytics into an organized layout.

### Key Components / Key Classes / Key Exports
- **`Overview`**: React functional component that renders the main diagnostic telemetry overview page, fetching states from the telemetry store and presenting structured metric cards.

### Integration Points
This module integrates directly with the `useTelemetryStore` custom hook to access global session telemetry states, including spatial metadata and real-time analytical metrics. It also imports vector icons from `lucide-react` to visually contextualize biological, kinematic, and technical metrics.

---

# Physiology Doc

### Purpose
The Physiology component is a React page module that visualizes cross-modal VR telemetry data, specifically correlating user movement intensity with cardiovascular activity. It provides researchers with real-time statistical insights and synchronized time-series line charts comparing head velocity and heart rate.

### Key Components / Key Exports
- **`Physiology`**: The main React functional component responsible for rendering the dashboard UI, processing telemetry data frames via memoization, and displaying performance summary cards and charts.

### Integration Points
This module integrates directly with the global `useTelemetryStore` state hook to consume raw VR frame records, and leverages Recharts library components to render responsive, dual-axis multi-metric charts.

---

# Rawdataexplorer Doc

### Purpose
RawDataExplorer is a diagnostic React component that provides a tabular view of low-level VR telemetry frames. It allows developers and researchers to directly inspect raw frame data, including head-mounted display (HMD) coordinates, tracking validity flags, and physiological metrics like heart rate.

### Key Components / Key Exports
- **`RawDataExplorer`**: The primary React functional component rendering a paginated, scrollable data table using TanStack Table.

### Integration Points
This component consumes telemetry frames from the global state store via `useTelemetryStore` and relies on `@tanstack/react-table` for core table management, pagination, and data rendering.

---

# Sessionexplorer Doc

### Purpose
This module provides a React-based relational query interface page for browsing, viewing details of, and editing VR telemetry session records. It renders interactive tables and modal dialogs to query and update metadata associated with experimental subjects and hardware.

### Key Components / Key Exports
- **`SessionExplorer`**: The primary React functional component managing state for sessions listings, modal visibility, data loading, error handling, and inline edits.
- **`SessionRecord`**: TypeScript interface defining the structural contract for session metadata objects fetched from the API.

### Integration Points
Interacts directly with a backend REST API running on `http://localhost:8000/api/sessions` via standard `fetch` requests for retrieving, inspecting, and updating telemetry session records.

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
pages/
├── Activation.tsx
├── DataQuality.tsx
├── Export.tsx
├── EyeTracking.tsx
├── Login.tsx
├── Metadata.tsx
├── NewSession.tsx
├── Overview.tsx
├── Physiology.tsx
├── README.md
├── RawDataExplorer.tsx
└── SessionExplorer.tsx
```