# Auto Installer Activity Central Data Manager Ingest Flow Export Actions Activity Main Hardware Pacing Loop

# Auto Installer Activity

```mermaid
activityDiagram
    start
    :verify_and_install_dependencies;
    :Locate requirements.txt;
    if (File exists?) then (yes)
        :Run pip install via subprocess;
        if (Installation success?) then (yes)
            :Log success;
            stop
        else (no)
            :Log critical error and exit;
            stop
        endif
    else (no)
        :Log error and return;
        stop
    endif
```

---

# Central Data Manager Ingest Flow

```mermaid
flowchart TD
    A[Start ingest_session] --> B[Calculate SHA-256 checksum]
    B --> C{Existing Session?}
    C -->|Yes, Same Checksum| D[Log Duplicate & Return no-op]
    C -->|Yes, Diff Checksum| E[Log Conflict & Reject]
    C -->|No| F[Write bytes to disk storage]
    F --> G[Re-read & Verify disk checksum]
    G --> H[Insert record into SQLite]
    H --> I[Log 'received' event]
    I --> J[Commit & Return success]
```

---

# Export Actions Activity

```mermaid
graph TD
    A[Start: Export Page Loaded] --> B{Metadata Loaded?}
    B -- No --> C[Display 'Load a Parquet session' message]
    B -- Yes --> D[Display Export Options & Context]
    
    D --> E1[Click: Raw Telemetry CSV]
    D --> E2[Click: Derived Metrics JSON]
    D --> E3[Click: Scientific Report PDF]
    D --> E4[Click: Sync to Central Server]
    
    E1 --> F1[Map frames to CSV & trigger Blob download]
    E2 --> F2[Construct JSON payload & trigger Blob download]
    E3 --> F3[Open printable HTML window and invoke window.print]
    E4 --> F4[POST to /api/sync/retry and update sync status]
```

---

# Main Hardware Pacing Loop

```mermaid
flowchart TD
    Start(["Engine calls _loop()"]) --> CheckGDPR{"Check GDPR Consent"}
    CheckGDPR -- "Consent Revoked" --> RaiseError["Raise GDPRConsentError"] --> Stop(["stop"])
    CheckGDPR -- "Consent Maintained" --> PollFrame["Call backend.poll_frame()<br/>(Blocks on xrWaitFrame)"]
    PollFrame --> ExtractHMD["Extract HMD Transforms"]
    PollFrame --> ExtractEye["Extract Eye Gaze Vectors"]
    PollFrame --> ExtractPupil["Extract Pupillometry"]
    ExtractHMD --> Compile["Compile TelemetryFrame<br/>(Flat Float32 Tensor)"]
    ExtractEye --> Compile
    ExtractPupil --> Compile
    Compile --> Context["Inject Scene ID Context"]
    Context --> Push["BiometricSynchronizer.push_frame(frame)<br/>(Non-blocking queue)"]
    Push --> Increment["Increment frames_recorded"]
    Increment --> CheckRunning{"is_running == true?"}
    CheckRunning -- Yes --> CheckGDPR
    CheckRunning -- No --> Teardown["Proceed to _teardown()"] --> Stop
```

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
activity/
├── README.md
└── main_hardware_pacing_loop.svg
```