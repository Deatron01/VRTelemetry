# Backends Architecture

```mermaid
graph TD
    A[Application Layer] --> B[Backends Init]
    B --> C[RuntimeCapabilityDiscovery]
    B --> D[OpenXRHeadlessBackend]
    C --> E[System Runtimes]
    D --> F[OpenXR Runtime]
```

---

# Backends Hal Architecture

```mermaid
graph TD
    subgraph HAL ["Hardware Abstraction Layer (src.backends)"]
        RCD["RuntimeCapabilityDiscovery"]
        OHB["OpenXRHeadlessBackend"]
    end

    App ["Spatial Engine / Client"] -->|"Discovers Capabilities"| RCD
    App -->|"Initializes Context"| OHB
```

---

# Call Graph Bootstrapper

```mermaid
flowchart TD
    Main["__main__"] --> Exec["execute_pipeline()"]
    Exec --> SetupLog["src.utils.logger.setup_logging()"]
    Exec --> ParseArgs["parse_arguments()"]
    Exec --> HardwareCheck{"args.gdpr_consent == True?"}
    HardwareCheck -- Yes --> ExtHW["RuntimeCapabilityDiscovery.extract_static_hardware_metadata()"]
    HardwareCheck -- No --> Exit1["sys.exit(1)"]
    ExtHW --> EngineInit["TelemetryEngine.__init__()"]
    EngineInit --> DBInit["DatabaseManager.__init__()"]
    EngineInit --> XRInit["OpenXRHeadlessBackend.__init__()"]
    EngineInit --> PQInit["AsyncParquetWriter.__init__()"]
    EngineInit --> SyncInit["BiometricSynchronizer.__init__()"]
    Exec --> EnforceID["engine.subject_metadata override"]
    Exec --> EngineStart["TelemetryEngine.start()"]
    EngineStart --> XRInitSys["OpenXRHeadlessBackend.initialize()"]
    EngineStart --> DBPersist["DatabaseManager.persist_experiment()"]
    EngineStart --> HWStart["HardwareMonitor.start()"]
    EngineStart --> PQStart["AsyncParquetWriter.start()"]
    EngineStart --> Loop["TelemetryEngine._loop()"]
    classDef entry fill:#e1bee7,stroke:#8e24aa,stroke-width:2px;
    classDef logic fill:#bbdefb,stroke:#2196f3,stroke-width:2px;
    classDef init fill:#c8e6c9,stroke:#4caf50,stroke-width:2px;
    class Main,Exec entry;
    class EngineStart,Loop,ExtHW logic;
    class EngineInit,DBInit,XRInit,PQInit,SyncInit init;
```

---

# Component Architecture

```mermaid
flowchart TB
    subgraph Bootstrapper ["main.py"]
        CLI["ArgParse CLI"]
        Discovery["RuntimeCapabilityDiscovery"]
    end
    subgraph Core ["Core Engine (engine.py)"]
        TE["TelemetryEngine"]
        Sync["BiometricSynchronizer"]
    end
    subgraph Hardware_Abstractions ["Backends & Drivers"]
        IVR["IVRBackend Interface"]
        OpenXR["OpenXRHeadlessBackend"]
        HW_Mon["HardwareMonitor"]
    end
    subgraph Storage ["Storage & I/O"]
        DB["DatabaseManager SQLite"]
        PQ["AsyncParquetWriter"]
    end
    CLI -->|"gdpr_consent, output, subject_id"| TE
    Discovery -->|"Hardware Topology Metadata"| TE
    TE -->|"Manages Metadata"| DB
    TE -->|"Monitors System"| HW_Mon
    TE -->|"Initializes & Polls"| OpenXR
    TE -->|"Passes Frames"| Sync
    IVR -.->|"Implements"| OpenXR
    Sync -->|"Feeds Buffer"| PQ
    note_main_thread["Main Thread: Blocked on xrWaitFrame"] -.-> TE
    note_async_thread["Async Thread: AsyncIO Event Loop"] -.-> Sync
    classDef interface fill:#f9f,stroke:#333,stroke-width:2px;
    class IVR interface;
```

---

# Core Module Architecture

```mermaid
graph TD
    CoreInit["src.core.__init__"]
    CoreInit --> TelemetryEngine["TelemetryEngine (engine)"]
    CoreInit --> TelemetryFrame["TelemetryFrame (datatypes)"]
    CoreInit --> BiometricSynchronizer["BiometricSynchronizer (synchronizer)"]
    CoreInit --> IVRBackend["IVRBackend (interfaces)"]
    CoreInit --> Exceptions["GDPRConsentError, HardwareBindingError (exceptions)"]
```

---

# Error Handling Flow

```mermaid
flowchart TD
    Run["Main Loop Running"]
    Event_KBI(["User presses Ctrl+C<br/>KeyboardInterrupt"])
    Event_GDPR(["GDPR Consent Revoked<br/>GDPRConsentError"])
    Event_Panic(["Hardware/API Panic<br/>Unhandled Exception"])
    Run --> Event_KBI
    Run --> Event_GDPR
    Run --> Event_Panic
    subgraph Teardown_Sequence ["Graceful Degradation & Teardown"]
        direction TB
        LogKBI["Log: 'Interrupted manually by operator'"]
        LogGDPR["Log: 'Compliance violation terminated tracking'"]
        LogCrit["Log: 'CRITICAL Unhandled framework panic'"]
        TeardownRoutine["Execute engine._teardown()"]
        Exit1(["sys.exit(1)"])
        Exit0(["sys.exit(0)"])
    end
    Event_KBI --> LogKBI
    Event_GDPR --> LogGDPR
    Event_Panic --> LogCrit
    LogKBI --> TeardownRoutine
    LogGDPR --> TeardownRoutine
    LogCrit --> TeardownRoutine
    TeardownRoutine --> Exit0
    Boot["Bootstrapper: main.py"] --> BootCheck{"GDPR Flag<br/>Passed?"}
    BootCheck -- No --> AbortBoot["Log Error & Abort"]
    AbortBoot --> Exit1
    classDef error fill:#ffcdd2,stroke:#f44336,stroke-width:2px;
    classDef warn fill:#fff9c4,stroke:#fbc02d,stroke-width:2px;
    classDef safe fill:#c8e6c9,stroke:#4caf50,stroke-width:2px;
    class Event_GDPR,Event_Panic,Exit1,AbortBoot error;
    class Event_KBI,LogKBI,LogGDPR,LogCrit warn;
    class TeardownRoutine,Exit0 safe;
```

---

# Eye Tracking Architecture

```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<interface>>
    }
    class EXTEyeGazeDriver
    class FBEyeTrackingSocialDriver
    class HTCEyeTrackingDriver
    class EyeTrackingFactory

    IEyeTrackingDriver <|.. EXTEyeGazeDriver
    IEyeTrackingDriver <|.. FBEyeTrackingSocialDriver
    IEyeTrackingDriver <|.. HTCEyeTrackingDriver
    EyeTrackingFactory --> IEyeTrackingDriver : creates
```

---

# Hardware Monitor Subsystem

```mermaid
sequenceDiagram
    participant Engine as TelemetryEngine
    participant HWMon as HardwareMonitor
    participant HWThread as Daemon Thread (Low-Hz)
    participant OS as OS (psutil)
    
    Engine->>HWMon: start()
    HWMon->>HWThread: spin_up(daemon=True)
    
    loop Every 1.0 Seconds (1Hz)
        HWThread->>OS: psutil.cpu_percent()
        OS-->>HWThread: CPU %
        HWThread->>OS: psutil.virtual_memory()
        OS-->>HWThread: RAM Usage
        
        HWThread->>HWMon: Store latest_state (Thread-Safe Variable)
    end
    
    note over Engine, HWMon: Main Loop pulling data at 90Hz
    loop 90 times per second
        Engine->>HWMon: get_latest_state()
        HWMon-->>Engine: Returns cached CPU/RAM values
        Engine->>Engine: Embeds CPU/RAM into TelemetryFrame
    end
    
    Engine->>HWMon: stop()
    HWMon->>HWThread: exit()
```

---

# Logger Architecture

```mermaid
graph TD
    A[Application Modules] -->|Uses| B[logger: VRTelemetry]
    B -->|Configured by| C[setup_logging]
    C -->|Writes to| D[Global Log File]
    C -->|Writes to| E[Console Stream]
    F[Session Start] -->|Calls| G[attach_session_log_capture]
    G -->|Writes to| H[Session-specific Log File]
    I[Session End] -->|Calls| J[detach_session_log_capture]
    J -->|Closes| H
```

---

# Logging Architecture

```mermaid
flowchart LR
    subgraph Sources ["Thread Sources"]
        Main["Main Thread<br/>Hardware Polling"]
        Async["Async Thread<br/>Parquet Writing"]
        Boot["Bootstrapper<br/>main.py"]
    end
    subgraph Logger ["Logger: 'vrtelemetry'"]
        Formatter["Formatter<br/>'%Y-%m-%d %H:%M:%S | %-8s | %s'"]
    end
    subgraph Destinations ["Outputs"]
        Stream["StreamHandler<br/>(stdout / Console)"]
        File["FileHandler<br/>'Logs/vr_telemetry_engine.log'"]
    end
    Main -- "logger.debug/info" --> Logger
    Async -- "logger.error/warn" --> Logger
    Boot -- "logger.info" --> Logger
    Logger --> Formatter
    Formatter --> Stream
    Formatter --> File
    classDef io fill:#bbdefb,stroke:#2196f3,stroke-width:2px,color:#000;
    class Stream,File io;
```

---

# Main Architecture

```mermaid
graph TD
    User[CLI / System Process] -->|execute_pipeline| EngineCLI[TelemetryEngine]
    WebClient[React / Web Frontend] -->|HTTP REST| API[FastAPI Web Service]

    subgraph API Router & Handlers
        API --> RecEP["/api/recording/start & stop"]
        API --> UploadEP["/api/upload-telemetry"]
        API --> SessEP["/api/sessions/*"]
        API --> AuthEP["/api/auth/*"]
        API --> LicEP["/api/license/*"]
        API --> SyncEP["/api/sync/*"]
    end

    subgraph Background Processing & Storage
        RecEP -->|Extract static capabilities| RCD[RuntimeCapabilityDiscovery]
        RecEP -->|Spawn Thread| EngineThread[TelemetryEngine Thread]
        UploadEP -->|Downsample & Sanitize| Pandas[Pandas Parquet Engine]
        SessEP --> SQLite[(SQLite: vr_metadata.db)]
        AuthEP --> LocalCache[LocalLicenseCache]
        LicEP --> Fingerprint[Hardware Fingerprint Generator]
        LicEP --> LocalCache
        SyncEP --> Uploader[SessionUploader]
    end

    subgraph External Network Services
        LocalCache <--> CentralServer[Central Server HTTP API]
        LicEP <--> CentralServer
        Uploader --> CentralServer
    end
```

---

# Main Bootstrap Architecture

```mermaid
graph TD
    A[DOM Root Element] -->|Target| B[ReactDOM.createRoot]
    B --> C[React.StrictMode]
    C --> D[App Component]
    D --> E[index.css Styles]
```

---

# Main Tsx Architecture

```mermaid
graph TD
    A[DOM Element: root] -->|ReactDOM.createRoot| B(React Root)
    B --> C[React.StrictMode]
    C --> D[App Component]
    D --> E[Global Styles: index.css]
```

---

# Module Dependencies

```mermaid
flowchart TD
    %% Main Entry Points
    Runner["src.tert_runner"] --> Main["src.main"]
    
    %% Main dependencies
    Main --> CoreEngine["src.core.engine"]
    Main --> Discovery["src.backends.discovery"]
    Main --> Logger["src.utils.logger"]
    Main --> Excep["src.core.exceptions"]
    
    %% Engine dependencies
    CoreEngine --> OpenXR["src.backends.openxr_headless"]
    CoreEngine --> Sync["src.core.synchronizer"]
    CoreEngine --> Writer["src.storage.parquet_writer"]
    CoreEngine --> DB["src.storage.database_manager"]
    CoreEngine --> HWMon["src.utils.hardware_monitor"]
    CoreEngine --> Excep
    
    %% Interfaces and Types
    OpenXR --> Interfaces["src.core.interfaces"]
    Sync --> DataTypes["src.core.datatypes"]
    Interfaces --> DataTypes
    
    %% Subsystems
    Sync --> Writer
    Sync --> HWMon
    
    classDef main fill:#ffe0b2,stroke:#ff9800,stroke-width:2px;
    classDef core fill:#c8e6c9,stroke:#4caf50,stroke-width:2px;
    classDef infra fill:#bbdefb,stroke:#2196f3,stroke-width:2px;
    
    class Main,Runner main;
    class CoreEngine,Sync,DataTypes,Interfaces,Excep core;
    class OpenXR,Writer,DB,HWMon,Discovery,Logger infra;
```

---

# Openxr Backend Architecture

```mermaid
classDiagram
    class IVRBackend {
        <<interface>>
        +initialize() bool
        +poll_frame(frame_index) TelemetryFrame
        +shutdown() void
    }
    class OpenXRBackend {
        -instance: xr.Instance
        -system_id: xr.SystemId
        -session: xr.Session
        -eye_driver: IEyeTrackingDriver
        +initialize() bool
        +poll_frame(frame_index) TelemetryFrame
        +shutdown() void
        -_setup_actions() void
        -_pump_events() void
    }
    IVRBackend <|-- OpenXRBackend : Implements
    OpenXRBackend --> IEyeTrackingDriver : Uses
    OpenXRBackend --> TelemetryFrame : Produces
```

---

# Openxr Headless Architecture

```mermaid
classDiagram
    class IVRBackend {
        <<interface>>
        +initialize() bool
        +poll_frame(frame_index: int) TelemetryFrame
        +shutdown()
    }
    class OpenXRHeadlessBackend {
        -instance: xr.Instance
        -system_id: xr.SystemId
        -session: xr.Session
        -app_space: xr.Space
        -eye_driver: IEyeTrackingDriver
        -is_pure_headless: bool
        +initialize() bool
        +_create_d3d11_binding()
        +_setup_actions()
        +_pump_events()
        +poll_frame(frame_index: int) TelemetryFrame
        +shutdown()
    }
    IVRBackend <|-- OpenXRHeadlessBackend : implements
    OpenXRHeadlessBackend --> IEyeTrackingDriver : uses
```

---

# Server Entrypoint Architecture

```mermaid
graph TD
    A[server_entrypoint.py] -->|Calls setup_logging| B(src.utils.logger)
    A -->|Hosts FastAPI app| C(src.main.app)
    A -->|Runs server via| D[uvicorn.run]
```

---

# Spatial Viewer Architecture

```mermaid
graph TD;
    A[useTelemetryStore] -->|Frames & Indices| B(VRRig)
    A -->|Frames & Indices| C(LivePoRCursor)
    A -->|Frames & Indices| D(AnalyticalLayers)
    B --> E[Three.js Canvas]
    C --> E
    D --> E
    F[User Controls] -->|Toggle Layers| E
```

---

# Storage Architecture

```mermaid
graph TD
    TelemetryPipeline -->|Raw Data| AsyncParquetWriter
    TelemetryPipeline -->|Metadata| DatabaseManager
    AsyncParquetWriter -->|Parquet Files| Disk[(Disk Storage)]
    DatabaseManager -->|SQLite DB| Disk
```

---

# Telemetry Core Architecture

```mermaid
graph TD
    CorePkg[src.core] --> Engine[TelemetryEngine]
    CorePkg --> Models[TelemetryFrame]
    CorePkg --> Sync[BiometricSynchronizer]
    CorePkg --> Interfaces[IVRBackend]
    CorePkg --> Exceptions[GDPRConsentError / HardwareBindingError]
```

---

# Thread Synchronization

```mermaid
flowchart TD
    subgraph Main_Thread ["Main Thread (Hardware Locked)"]
        direction TB
        xrWait[OpenXR xrWaitFrame<br/>Blocks strictly to hardware vsync]
        Poll[poll_frame<br/>Captures TelemetryFrame]
        Push[BiometricSynchronizer.push_frame]
        xrWait --> Poll --> Push
    end

    subgraph Memory_Bridge ["Memory / Sync Layer"]
        RingBuffer[(Thread-Safe Queue / Ring Buffer)]
    end

    subgraph Async_Thread ["Async Event Loop Thread"]
        direction TB
        Pop[Pop Frame from Buffer]
        Batch[Batch Frames in Memory]
        WriteIO[AsyncParquetWriter.write_batch<br/>Awaited Disk I/O]
        Pop --> Batch --> WriteIO
    end

    Push == "Non-blocking Push" ==> RingBuffer
    RingBuffer == "Async Pull" ==> Pop

    classDef hardware fill:#ffe0b2,stroke:#ff9800,stroke-width:2px,color:#000;
    classDef memory fill:#c8e6c9,stroke:#4caf50,stroke-width:2px,color:#000;
    classDef io fill:#bbdefb,stroke:#2196f3,stroke-width:2px,color:#000;
    
    class Main_Thread hardware;
    class Memory_Bridge memory;
    class Async_Thread io;
```

---

# Utils Layer Architecture

```mermaid
graph TD
    A[Application Core] --> B[utils.__init__]
    B --> C[logger]
    B --> D[HardwareMonitor]
```

---
