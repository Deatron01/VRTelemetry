sequenceDiagram
    participant CLI as main.py
    participant Engine as TelemetryEngine
    participant DB as DatabaseManager
    participant XR as OpenXRHeadlessBackend
    participant Sync as BiometricSynchronizer
    participant Disk as AsyncParquetWriter
    participant HW as Hardware

    CLI->>CLI: parse_arguments()
    CLI->>CLI: Check --gdpr-consent
    alt No Consent
        CLI-->>User: GDPRConsentError (Abort)
    end

    CLI->>Hardware: extract_static_hardware_metadata()
    Hardware-->>CLI: Hardware topology dict
    
    CLI->>Engine: __init__(output_dir, gdpr_consent, metadata)
    Engine->>Engine: Generate session_id
    Engine->>DB: Instantiate
    Engine->>XR: Instantiate
    Engine->>Disk: Instantiate(AsyncParquetWriter)
    Engine->>Sync: Instantiate(writer, hardware_monitor)
    
    CLI->>Engine: start()
    Engine->>XR: initialize()
    XR-->>Engine: True (Bound successfully)
    
    Engine->>DB: persist_experiment(subject_metadata)
    
    Engine->>Disk: start()
    Engine->>Engine: Spin up AsyncConsumerThread
    note right of Engine: Async thread runs BiometricSynchronizer event loop
    
    loop Real-time Polling (e.g., 90Hz-120Hz)
        Engine->>XR: poll_frame(frames_recorded)
        note over XR: Blocks on xrWaitFrame (Hardware Pacing)
        XR-->>Engine: TelemetryFrame (Flat Tensor)
        Engine->>Engine: Inject contextual marker (scene_id)
        Engine->>Sync: push_frame(frame_data)
        note over Sync: Pushes to non-blocking ring buffer
    end
    
    note over Engine: On Shutdown (KeyboardInterrupt)
    Engine->>Engine: _teardown()
    Engine->>Sync: stop()
    Engine->>Disk: stop()
    Engine->>XR: shutdown()