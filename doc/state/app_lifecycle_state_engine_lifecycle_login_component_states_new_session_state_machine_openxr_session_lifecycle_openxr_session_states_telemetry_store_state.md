# App Lifecycle State

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

---

# Engine Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Uninitialized

    Uninitialized --> ValidatingConsent : CLI Bootstrapper triggered
    ValidatingConsent --> Terminated : GDPR Consent Missing (Abort)
    ValidatingConsent --> HardwareDiscovery : --gdpr-consent True
    
    HardwareDiscovery --> Initializing : Metadata Collected
    
    state Initializing {
        [*] --> BindingOpenXR
        BindingOpenXR --> SpinningUpThreads
        SpinningUpThreads --> PersistingSQL
        PersistingSQL --> [*]
    }
    
    Initializing --> Running : Initialization Success
    Initializing --> Terminated : OpenXR Bind Failure
    
    state Running {
        [*] --> WaitingForFrame
        WaitingForFrame --> CapturingData : xrWaitFrame tick
        CapturingData --> PushingToBuffer
        PushingToBuffer --> CheckingConsentIteration
        CheckingConsentIteration --> WaitingForFrame : Consent Maintained
    }
    
    Running --> Teardown : KeyboardInterrupt (Operator Stop)
    Running --> Teardown : GDPR Consent Revoked (Runtime Exception)
    
    Teardown --> FlushingBuffers
    FlushingBuffers --> ClosingXRSpace
    ClosingXRSpace --> Terminated
    
    Terminated --> [*]
```

---

# Login Component States

```mermaid
stateDiagram-v2
    [*] --> LoginMode
    state LoginMode {
        [*] --> IdleLogin
        IdleLogin --> SubmittingLogin : Click 'Sign In'
        SubmittingLogin --> ErrorLogin : API Error / Invalid Fields
        ErrorLogin --> IdleLogin : Retry
        SubmittingLogin --> [*] : Success (onAuthenticated)
    }
    LoginMode --> RegisterMode : Click 'Register your lab'
    state RegisterMode {
        [*] --> IdleRegister
        IdleRegister --> SubmittingRegister : Click 'Create Account'
        SubmittingRegister --> ErrorRegister : API Error / Missing Lab Name
        ErrorRegister --> IdleRegister : Retry
        SubmittingRegister --> LoginMode : Success (flips to login)
    }
    RegisterMode --> LoginMode : Click 'Sign in'
```

---

# New Session State Machine

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Recording : handleStart() [gdpr_consent == true]
    Recording --> Idle : handleStop()
```

---

# Openxr Session Lifecycle

```mermaid
stateDiagram-v2
    [*] --> XR_SESSION_STATE_UNKNOWN
    
    XR_SESSION_STATE_UNKNOWN --> XR_SESSION_STATE_IDLE : xrBeginSession()
    
    XR_SESSION_STATE_IDLE --> XR_SESSION_STATE_READY : Runtime acknowledges session
    
    state "Active Headless Tracking" as ActiveTracking {
        XR_SESSION_STATE_READY --> XR_SESSION_STATE_SYNCHRONIZED : App synced with display
        XR_SESSION_STATE_SYNCHRONIZED --> XR_SESSION_STATE_VISIBLE : (Skipped by Headless)
        XR_SESSION_STATE_VISIBLE --> XR_SESSION_STATE_FOCUSED : (Skipped by Headless)
        
        %% In headless mode, we can pull data while merely synchronized
        note right of XR_SESSION_STATE_SYNCHRONIZED
            VRTelemetry polls biometric 
            data in this state. It never 
            requests Visibility or Focus.
        end note
    }
    
    XR_SESSION_STATE_SYNCHRONIZED --> XR_SESSION_STATE_STOPPING : VR App Closes / Quit
    
    XR_SESSION_STATE_STOPPING --> XR_SESSION_STATE_IDLE : xrEndSession()
    
    XR_SESSION_STATE_IDLE --> XR_SESSION_STATE_EXITING : xrDestroySession()
    
    XR_SESSION_STATE_EXITING --> [*]
```

---

# Openxr Session States

```mermaid
stateDiagram-v2
    [*] --> UNKNOWN
    UNKNOWN --> READY : EventDataSessionStateChanged
    READY --> SYNCHRONIZED : begin_session()
    SYNCHRONIZED --> VISIBLE : wait_frame()
    VISIBLE --> FOCUSED
    FOCUSED --> VISIBLE
    VISIBLE --> SYNCHRONIZED
    SYNCHRONIZED --> STOPPING : Session Stop
    STOPPING --> IDLE : end_session()
    IDLE --> [*]
```

---

# Telemetry Store State

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Loaded : loadSession()
    state Loaded {
        [*] --> Paused
        Paused --> Playing : togglePlayback()
        Playing --> Paused : togglePlayback()
    }
```

---
