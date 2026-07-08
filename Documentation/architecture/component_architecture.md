flowchart TB
    subgraph Bootstrapper ["main.py"]
        CLI[ArgParse CLI]
        Discovery[RuntimeCapabilityDiscovery]
    end

    subgraph Core ["Core Engine (engine.py)"]
        TE[TelemetryEngine]
        Sync[BiometricSynchronizer]
    end

    subgraph Hardware_Abstractions ["Backends & Drivers"]
        IVR[IVRBackend Interface]
        OpenXR[OpenXRHeadlessBackend]
        HW_Mon[HardwareMonitor]
    end

    subgraph Storage ["Storage & I/O"]
        DB[DatabaseManager SQLite]
        PQ[AsyncParquetWriter]
    end

    CLI -->|gdpr_consent, output, subject_id| TE
    Discovery -->|Hardware Topology Metadata| TE

    TE *-- DB : Manages Metadata
    TE *-- HW_Mon : Monitors System
    TE *-- OpenXR : Initializes & Polls
    TE *-- Sync : Passes Frames

    IVR <|-- OpenXR : Implements
    
    Sync *-- PQ : Feeds Buffer

    %% Threading logic
    note_main_thread>Main Thread: Blocked on xrWaitFrame] -.- TE
    note_async_thread>Async Thread: AsyncIO Event Loop] -.- Sync

    classDef interface fill:#f9f,stroke:#333,stroke-width:2px;
    class IVR interface;