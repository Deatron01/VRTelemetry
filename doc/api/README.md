# Backend Ocolus Api Backend Steamvr Api Central Server Api Cli Argument Flow Ext Eye Gaze Architecture Eye Tracking Factory Sequence Fb Social Driver Api Htc Tracker Api Main Api Ar Combined

# Backend Ocolus Api

```mermaid
classDiagram
    class IVRBackend {
        <<interface>>
        +initialize() bool
        +poll_frame(frame_index: int) TelemetryFrame
        +shutdown() None
    }
    class OculusBackend {
        -session
        -luid
        -hmd_desc
        -has_eye_tracking: bool
        +__init__()
        +initialize() bool
        +poll_frame(frame_index: int) TelemetryFrame
        +shutdown() None
    }
    IVRBackend <|-- OculusBackend
```

---

# Backend Steamvr Api

```mermaid
classDiagram
    class IVRBackend {
        <<interface>>
    }
    class SteamVROverlayBackend {
        +vr_system
        +vr_overlay
        +overlay_handle
        +initialize() bool
        +poll_frame(frame_index: int) TelemetryFrame
        +shutdown() void
    }
    IVRBackend <|-- SteamVROverlayBackend
```

---

# Central Server Api

```mermaid
graph TD;
    Client[Desktop/Client App] -->|/auth/*| AuthMgr[AuthManager]
    Client -->|/license/*| LicenseMgr[LicenseManager]
    Client -->|/data/*| DataMgr[CentralDataManager]
    Admin[Admin Dashboard] -->|/admin/* (require_admin)| Server[FastAPI Server]
    Server --> AuthMgr
    Server --> LicenseMgr
    Server --> DataMgr
```

---

# Cli Argument Flow

```mermaid
flowchart TD
    Start(["Execute: python -m src.main"]) --> Parse["argparse.ArgumentParser"]
    Parse --> ArgConsent["--gdpr-consent<br/>(Action: store_true)"]
    Parse --> ArgOutput["--output<br/>(Type: str, Default: 'Sessions')"]
    Parse --> ArgSub["--subject-id<br/>(Type: str, Default: 'SUB_UNKN_01')"]
    ArgConsent --> ValConsent{"Is True?"}
    ValConsent -- No --> LogAbort["logger.error<br/>Launch aborted"] --> Exit(["sys.exit(1)"])
    ValConsent -- Yes --> Topology["RuntimeCapabilityDiscovery.extract()"]
    ArgOutput --> MergeConfig
    ArgSub --> MergeConfig
    Topology --> MergeConfig["Merge into Configuration Dicts"]
    MergeConfig --> Instantiate["Instantiate TelemetryEngine"]
    Instantiate --> EnforceID["engine.subject_metadata[...] = args.subject_id"]
    EnforceID --> StartEngine["engine.start()"]
    StartEngine --> End(["Tracking Session Active"])
    classDef input fill:#e1bee7,stroke:#8e24aa,stroke-width:2px;
    classDef check fill:#ffe0b2,stroke:#ff9800,stroke-width:2px;
    classDef fail fill:#ffcdd2,stroke:#f44336,stroke-width:2px;
    class ArgConsent,ArgOutput,ArgSub input;
    class ValConsent check;
    class LogAbort,Exit fail;
```

---

# Ext Eye Gaze Architecture

```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<interface>>
        +get_extension_name() str
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns) void
        +shutdown() void
    }
    class EXTEyeGazeDriver {
        -session: xr.Session
        -app_space: xr.Space
        -action_set: xr.ActionSet
        -eye_gaze_action: xr.Action
        -eye_space: xr.Space
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns) void
        +shutdown() void
    }
    IEyeTrackingDriver <|-- EXTEyeGazeDriver
```

---

# Eye Tracking Factory Sequence

```mermaid
sequenceDiagram
    participant Client
    participant EyeTrackingFactory
    participant DriverClass as IEyeTrackingDriver

    Client->>EyeTrackingFactory: register_driver(driver_class)
    EyeTrackingFactory->>DriverClass: get_priority()
    Note over EyeTrackingFactory: Sorts registry by priority descending

    Client->>EyeTrackingFactory: create_best_driver(available_extensions)
    loop For each driver in registry
        EyeTrackingFactory->>DriverClass: get_extension_name()
        alt Extension matches available_extensions
            EyeTrackingFactory->>DriverClass: instantiate driver
            EyeTrackingFactory-->>Client: return driver_instance
        end
    end
    Note over EyeTrackingFactory: Returns None if no matching driver found
```

---

# Fb Social Driver Api

```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<interface>>
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns)
        +shutdown()
    }

    class FBEyeTrackingSocialDriver {
        -instance: xr.Instance
        -session: xr.Session
        -app_space: xr.Space
        -eye_tracker: c_void_p
        -_xrCreateEyeTrackerFB
        -_xrGetEyeGazesFB
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns)
        +shutdown()
    }

    IEyeTrackingDriver <|-- FBEyeTrackingSocialDriver
```

---

# Htc Tracker Api

```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<interface>>
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns) void
        +shutdown() void
    }
    class HTCEyeTrackingDriver {
        -instance: xr.Instance
        -session: xr.Session
        -app_space: xr.Space
        -facial_tracker: any
        -gaze_action_set: xr.ActionSet
        -gaze_pose_action: xr.Action
        -gaze_space: xr.Space
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns) void
        +shutdown() void
    }
    IEyeTrackingDriver <|-- HTCEyeTrackingDriver
```

---

# Main Api Architecture

```mermaid
graph TD
    Client[React Frontend / CLI] -->|HTTP Requests| FastAPI[VRTelemetry FastAPI App]
    
    subgraph FastAPI Endpoints
        FastAPI -->|POST /api/auth/*| Auth[Authentication Service]
        FastAPI -->|POST /api/recording/*| Recording[Session Recording Engine]
        FastAPI -->|GET/PUT /api/sessions/*| Sessions[SQLite Metadata Manager]
        FastAPI -->|POST /api/upload-telemetry| Upload[Parquet / Pandas Processor]
        FastAPI -->|GET/POST /api/license/*| License[License & Activation]
    end

    Recording -->|Spawns Thread| Engine[TelemetryEngine]
    Engine -->|Hardware Discovery| Hardware[Runtime Capabilities]
    Sessions -->|Query/Update| DB[(Sessions/vr_metadata.db)]
    License -->|Heartbeat / Cache| Cache[LocalLicenseCache]
```

---

# Main Api Workflow

```mermaid
graph TD
    Client[Frontend / Client] -->|HTTP POST/GET| App[FastAPI app instance]
    App -->|Manages Sessions| SQLite[(SQLite DB)]
    App -->|Controls| Engine[TelemetryEngine Thread]
    Engine -->|Collects Biometrics| Hardware[XR Hardware / UDP Stream]
    App -->|Heartbeats & Sync| CentralServer[Central Authority Server]
```

---

# Oculus Backend Api

```mermaid
classDiagram
direction LR
class IVRBackend {
    <<interface>>
    +initialize() bool
    +poll_frame(frame_index) TelemetryFrame
    +shutdown() void
}
class OculusBackend {
    -session
    -luid
    -hmd_desc
    -has_eye_tracking
    +initialize() bool
    +poll_frame(frame_index) TelemetryFrame
    +shutdown() void
}
IVRBackend <|-- OculusBackend
```

---

# Runtime Capability Discovery

```mermaid
sequenceDiagram
    participant Client
    participant RuntimeCapabilityDiscovery
    participant OpenXR

    Client->>RuntimeCapabilityDiscovery: extract_static_hardware_metadata()
    RuntimeCapabilityDiscovery->>OpenXR: xr.enumerate_instance_extension_properties()
    OpenXR-->>RuntimeCapabilityDiscovery: extension list
    RuntimeCapabilityDiscovery->>OpenXR: xr.create_instance(...) & xr.get_system(...)
    OpenXR-->>RuntimeCapabilityDiscovery: runtime properties & system properties
    RuntimeCapabilityDiscovery->>OpenXR: xr.destroy_instance(...)
    RuntimeCapabilityDiscovery-->>Client: metadata dictionary
```

---

# Runtime Capability Discovery Api

```mermaid
classDiagram
    class RuntimeCapabilityDiscovery {
        +extract_static_hardware_metadata() Dict~str, Any~
    }
```

---

# Server Api

```mermaid
graph TD
    Client[Desktop / Admin Client] -->|HTTP Requests| App[FastAPI app]
    App -->|Auth Management| AuthMgr[AuthManager]
    App -->|License Ops| LicenseMgr[LicenseManager]
    App -->|Data Ingestion| DataMgr[CentralDataManager]
    App -->|Admin UI Mount| Static[StaticFiles /admin-ui]
```

---

# Session Explorer Api Flow

```mermaid
sequenceDiagram
    participant UI as SessionExplorer (React)
    participant API as FastAPI Backend (/api/sessions)
    UI->>API: GET /api/sessions
    API-->>UI: Return SessionRecord[]
    UI->>API: GET /api/sessions/{id}
    API-->>UI: Return Session Details
    UI->>API: PUT /api/sessions/{id}
    API-->>UI: Confirm Update
```

---

# Vr Telemetry Api

```mermaid
graph TD
    Client[Web Frontend / CLI] -->|HTTP Requests| FastAPI[FastAPI App App]
    FastAPI -->|Telemetry Upload| Telemetry[Telemetry Engine]
    FastAPI -->|SQLite Metadata| DB[(Sessions DB)]
    FastAPI -->|Auth/License Check| Central[Central Server]
    FastAPI -->|Local State| Cache[Local License Cache]
```

---

# Vrtelemetry Api Architecture

```mermaid
graph TD
    subgraph Client Application / UI
        UI[Web Console / React Frontend]
    end

    subgraph Main Application Module [src/main.py]
        API[FastAPI Application]
        WorkerThread[Engine Worker Thread]
        Sanitizer[Data Sanitizer & Downsampler]
    end

    subgraph Core Telemetry Engine
        TE[TelemetryEngine]
        Discovery[RuntimeCapabilityDiscovery]
    end

    subgraph Storage & Cache
        SQLite[(SQLite Sessions DB)]
        Cache[LocalLicenseCache]
    end

    subgraph External System
        Central[Central Management Server]
    end

    UI -->|POST /api/recording/start| API
    API -->|Discover HW Capabilities| Discovery
    API -->|Spawn Async Thread| WorkerThread
    WorkerThread -->|Execute| TE
    
    UI -->|POST /api/upload-telemetry| API
    API -->|Parse & Downsample Parquet| Sanitizer
    
    UI -->|GET /api/sessions| API
    API -->|Query Metadata| SQLite
    
    UI -->|POST /api/auth & /api/license| API
    API -->|Proxy Requests| Central
    API -->|Cache Session & Token| Cache
```

---

---
