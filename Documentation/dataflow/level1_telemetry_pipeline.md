flowchart LR
    %% External Entities
    Subject([VR Test Subject])
    HMD[VR Hardware / Headset]
    App[External VR App]

    %% Processes
    Proc_Poll((1.0 Hardware<br/>Acquisition))
    Proc_Sync((2.0 Context<br/>Injection))
    Proc_Write((3.0 Storage<br/>Serialization))

    %% Data Stores
    DS_Meta[(SQLite DB<br/>Metadata)]
    DS_Parquet[(Apache Parquet<br/>Time-Series)]

    %% Flow
    Subject -- "Eye Gazes, Kinematics" --> HMD
    App -- "Scene Context ID" --> Proc_Sync
    HMD -- "Raw Sensor Vectors" --> Proc_Poll
    
    Proc_Poll -- "1D TelemetryFrame" --> Proc_Sync
    Proc_Sync -- "Enriched Frame" --> Proc_Write
    
    Proc_Sync -- "Subject Metadata<br/>(on init)" --> DS_Meta
    Proc_Write -- "Columnar Float32 Data<br/>(90-120Hz)" --> DS_Parquet

    %% Styling
    classDef process fill:#e1bee7,stroke:#8e24aa,stroke-width:2px,color:#000;
    class Proc_Poll,Proc_Sync,Proc_Write process;