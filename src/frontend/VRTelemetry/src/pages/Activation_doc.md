### Purpose
This module provides the Activation page component for the VRTelemetry frontend, enabling users to register un-licensed machines using an administrative license key. It renders a clean, modern form interface to securely transmit license credentials to the backend API and update the application lifecycle state upon success.

### Key Components / Key Classes / Key Exports
- **`Activation`**: A React functional component that manages local form state, handles user input validation, invokes the remote activation endpoint, and renders error alerts or loading indicators.
- **`ActivationProps`**: Interface defining the component contract, specifically exposing the `onActivated` callback triggered upon successful license verification.

### Integration Points
Interacts directly with the backend REST API via a `POST` request to `http://localhost:8000/api/license/activate` passing the user-supplied license key. It invokes the parent-provided `onActivated` callback to transition the application state when activation succeeds.
