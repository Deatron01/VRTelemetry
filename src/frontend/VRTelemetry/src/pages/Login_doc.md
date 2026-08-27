### Purpose
This module provides the authentication and user registration interface for the VRTelemetry Research Studio application. It allows researchers to sign into their accounts or register new organization labs to access telemetry workspaces.

### Key Components / Key Classes / Key Exports
- **`Login`**: React functional component that renders the authentication form, manages internal form state, handles switching between login and registration modes, and processes network authentication requests.

### Integration Points
Interacts with backend authentication endpoints (`/api/auth/login` and `/api/auth/register`) via HTTP POST requests and invokes the `onAuthenticated` callback prop upon successful user sign-in to propagate session data.
