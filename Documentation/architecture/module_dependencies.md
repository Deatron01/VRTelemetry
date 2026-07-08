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