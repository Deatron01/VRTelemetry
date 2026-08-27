### Purpose
This module provides a React-based relational query interface page for browsing, viewing details of, and editing VR telemetry session records. It renders interactive tables and modal dialogs to query and update metadata associated with experimental subjects and hardware.

### Key Components / Key Exports
- **`SessionExplorer`**: The primary React functional component managing state for sessions listings, modal visibility, data loading, error handling, and inline edits.
- **`SessionRecord`**: TypeScript interface defining the structural contract for session metadata objects fetched from the API.

### Integration Points
Interacts directly with a backend REST API running on `http://localhost:8000/api/sessions` via standard `fetch` requests for retrieving, inspecting, and updating telemetry session records.
