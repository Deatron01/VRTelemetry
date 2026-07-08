flowchart LR
    subgraph Sources ["Thread Sources"]
        Main[Main Thread<br/>Hardware Polling]
        Async[Async Thread<br/>Parquet Writing]
        Boot[Bootstrapper<br/>main.py]
    end

    subgraph Logger ["Logger: 'vrtelemetry'"]
        Formatter[Formatter<br/>'%Y-%m-%d %H:%M:%S | %-8s | %s']
    end

    subgraph Destinations ["Outputs"]
        Stream[StreamHandler<br/>(stdout / Console)]
        File[FileHandler<br/>'Logs/vr_telemetry_engine.log']
    end

    Main -- "logger.debug/info" --> Logger
    Async -- "logger.error/warn" --> Logger
    Boot -- "logger.info" --> Logger
    
    Logger --> Formatter
    Formatter --> Stream
    Formatter --> File

    classDef io fill:#bbdefb,stroke:#2196f3,stroke-width:2px,color:#000;
    class Stream,File io;