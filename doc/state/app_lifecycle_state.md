```mermaid
stateDiagram-v2
    [*] --> CheckingAuth
    CheckingAuth --> Unauthenticated : Not Logged In
    CheckingAuth --> CheckingLicense : Authenticated
    Unauthenticated --> CheckingAuth : Login Success
    CheckingLicense --> InactiveLicense : License Invalid/Inactive
    CheckingLicense --> ActiveDashboard : License Active
    InactiveLicense --> ActiveDashboard : Activation Success
    ActiveDashboard --> Unauthenticated : Logout
```