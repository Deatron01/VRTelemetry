```mermaid
sequenceDiagram
    participant HW as OpenXR Hardware Thread
    participant Sync as BiometricSynchronizer
    participant Loop as AsyncIO Loop
    participant Writer as AsyncParquetWriter

    HW->>Sync: push_frame(TelemetryFrame)
    Note over Sync: Appends to thread-safe deque
    Loop->>Sync: _consume_loop() runs periodically
    Sync->>Sync: Pop batch from deque
    Sync->>Writer: writer.push(frame_tuple)
```
