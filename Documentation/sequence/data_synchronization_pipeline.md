sequenceDiagram
    participant Main as Main Thread (Hardware)
    participant Sync as BiometricSynchronizer
    participant Queue as asyncio.Queue (Ring Buffer)
    participant Async as AsyncIO Consumer Thread
    participant Writer as AsyncParquetWriter

    note over Main, Sync: High-Frequency Domain (90-120Hz)
    Main->>Sync: push_frame(TelemetryFrame)
    Sync->>Queue: put_nowait(TelemetryFrame)
    
    note over Sync: If queue is full (disk IO extremely delayed)
    alt Queue Full Mitigation
        Sync->>Queue: Drop oldest frame (pop)
        Sync->>Queue: put_nowait(TelemetryFrame)
        Sync->>Logger: log_warning("Frame dropped to preserve real-time capacity")
    end
    
    note over Async, Writer: Decoupled Disk I/O Domain
    loop Every event loop tick
        Async->>Queue: get() (Awaits next frame)
        Queue-->>Async: TelemetryFrame
        Async->>Writer: add_frame_to_batch(TelemetryFrame)
        
        opt If Batch Size Reached OR Timeout
            Async->>Writer: write_batch_to_disk()
            note over Writer: Serializes flat tensors to Apache Parquet
            Writer-->>Async: Await Complete
        end
    end