from pathlib import Path

# A javított, tökéletesen formázott Mermaid kódok
FIXED_DIAGRAMS = {
    "component_architecture.md": """```mermaid
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
```""",
    "error_handling_flow.md": """```mermaid
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
```""",
    "cli_argument_flow.md": """```mermaid
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
```""",
    "logging_architecture.md": """```mermaid
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
```""",
    "call_graph_bootstrapper.md": """```mermaid
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
```""",
    "ci_cd_execution_matrix.md": """```mermaid
flowchart LR
    Commit["Push / PR to Main"] --> GH_Actions["GitHub Actions Runner"]
    GH_Actions --> Linting["Flake8 / Black Linter"]
    Linting --> Matrix{"OS & Python Matrix"}
    Matrix --> Win310["Windows - Python 3.10"]
    Matrix --> Win311["Windows - Python 3.11"]
    Matrix --> Win312["Windows - Python 3.12"]
    Matrix --> Lin311["Ubuntu - Python 3.11<br/>(Logic Only)"]
    Win310 --> ToxRun["Run Tox: -m 'not hardware'"]
    Win311 --> ToxRun
    Win312 --> ToxRun
    Lin311 --> ToxRun
    ToxRun --> Aggregate["Aggregate Pytest Coverage"]
    Aggregate --> Status{"Coverage > 85%?"}
    Status -- Yes --> Merge["Allow PR Merge"]
    Status -- No --> Block["Block PR Merge"]
    classDef pipeline fill:#cfd8dc,stroke:#607d8b,stroke-width:2px;
    classDef success fill:#c8e6c9,stroke:#4caf50,stroke-width:2px;
    classDef fail fill:#ffcdd2,stroke:#f44336,stroke-width:2px;
    class Linting,Matrix,ToxRun,Aggregate pipeline;
    class Merge success;
    class Block fail;
```""",
    "ai_post_processor_flow.md": """```mermaid
flowchart TD
    Raw["Raw Parquet Input<br/>vr_telemetry_TIMESTAMP.parquet"] --> Read["Read as PyArrow Table / Pandas DataFrame"]
    Read --> V1{"Check for Sensor Dropouts<br/>(e.g., Blinking)"}
    V1 -- Missing Data --> FF["Forward-Fill (ffill)<br/>Preserve Last Known Vector"]
    V1 -- No Missing Data --> M2
    FF --> M2
    M2["Temporal Smoothing Pipeline"] --> EMA_Eye["Apply Exponential Moving Average<br/>(EMA) to Eye Gaze Vectors"]
    EMA_Eye --> EMA_Kin["Apply EMA to High-Frequency<br/>HMD Kinematics"]
    EMA_Kin --> ZScore["Z-Score Standardization<br/>(Normalize 0 Mean, 1 Variance)"]
    ZScore --> Output["Export AI-Ready Parquet<br/>vr_telemetry_TIMESTAMP_ai_ready.parquet"]
    Output -.-> Model["PyTorch DataLoader / DL Model"]
    classDef process fill:#e1bee7,stroke:#8e24aa,stroke-width:2px,color:#000;
    classDef io fill:#bbdefb,stroke:#2196f3,stroke-width:2px,color:#000;
    class Raw,Output,Model io;
    class FF,EMA_Eye,EMA_Kin,ZScore process;
```""",
    "biometric_vector_assembly.md": """```mermaid
flowchart LR
    subgraph OpenXR_Runtime ["OpenXR DisplayTime Frame"]
        HMD["HMD Pose (LocateSpace)"]
        EyeGaze["Eye Gazes (XR_EXT_eye_gaze_interaction)"]
        Pupil["Pupillometry (Vendor Extension)"]
    end
    subgraph TelemetryFrame_Construction ["TelemetryFrame (1D Flat Array)"]
        direction TB
        T_Timestamp["[0] timestamp: float64"]
        T_HMD["[1-7] hmd_pos_x, y, z <br/> hmd_rot_x, y, z, w"]
        T_Gaze["[8-13] left_gaze_x, y, z <br/> right_gaze_x, y, z"]
        T_Pupil["[14-15] pupil_dilation_left, right"]
    end
    HMD -->|"Extract Position (Vector3) & Orientation (Quaternion)"| T_HMD
    EyeGaze -->|"Extract Left & Right Direction Vectors (Vector3)"| T_Gaze
    Pupil -->|"Extract Floats (mm)"| T_Pupil
    T_Timestamp --> ParquetRow
    T_HMD --> ParquetRow
    T_Gaze --> ParquetRow
    T_Pupil --> ParquetRow
    ParquetRow[("Appended to PyArrow Batch")]
    classDef runtime fill:#cfd8dc,stroke:#607d8b,stroke-width:2px;
    classDef frame fill:#e1bee7,stroke:#8e24aa,stroke-width:2px;
    class HMD,EyeGaze,Pupil runtime;
    class T_Timestamp,T_HMD,T_Gaze,T_Pupil frame;
```""",
    "testing_architecture.md": """```mermaid
flowchart TD
    Tox["Tox: Cross-Env Testing<br/>(Python 3.10, 3.11, 3.12)"] --> Pytest
    Pytest{"Pytest Test Suite"}
    Pytest -- "pytest tests/unit/" --> Unit["Unit Tests<br/>(Core Logic, Math, Validation)"]
    Pytest -- "pytest tests/integration/" --> Integ["Integration Tests<br/>(Pipeline, Storage IO)"]
    Pytest -- "pytest tests/performance/" --> Perf["Performance Tests<br/>(10k-Frame Stress Tests)"]
    Unit --> Mock["Mocked Hardware API<br/>Pytest-Mock"]
    Integ --> Temp["Temporary Directory<br/>Parquet Read/Write"]
    Perf --> MarkHardware{"Has @pytest.mark.hardware?"}
    MarkHardware -- "Yes (Running Locally)" --> RealHMD["Connects to Physical HMD"]
    MarkHardware -- "No (Running in CI/CD)" --> Skip["Skipped automatically via<br/>-m 'not hardware'"]
    classDef test fill:#e1bee7,stroke:#8e24aa,stroke-width:2px,color:#000;
    classDef hardware fill:#ffe0b2,stroke:#ff9800,stroke-width:2px,color:#000;
    class Unit,Integ,Perf test;
    class RealHMD hardware;
```""",
    "main_hardware_pacing_loop.md": """```mermaid
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
```""",
    "teardown_activity.md": """```mermaid
flowchart TD
    Start(["Trigger Teardown<br/>(KeyboardInterrupt/GDPR Violation)"]) --> Flag["is_running = False"]
    Flag --> SyncStop["BiometricSynchronizer.stop()"]
    SyncStop --> CheckAsync{"Async Loop running?"}
    CheckAsync -- Yes --> StopLoop["async_loop.call_soon_threadsafe(stop)"]
    CheckAsync -- No --> CheckThread
    StopLoop --> CheckThread{"Async Thread exists?"}
    CheckThread -- Yes --> Join["async_thread.join(timeout=3.0)"]
    CheckThread -- No --> HWStop
    Join --> HWStop["HardwareMonitor.stop()"]
    HWStop --> WriterStop["AsyncParquetWriter.stop()"]
    WriterStop --> XRStop["OpenXRHeadlessBackend.shutdown()<br/>(Releases API handles)"]
    XRStop --> Log["Log Finalization (Frames recorded)"]
    Log --> Stop(["stop"])
```""",
    "contribution_workflow.md": """```mermaid
flowchart TD
    Start(["Start"]) --> Fork["Fork VRTelemetry Repository"]
    Fork --> Clone["Clone Local Copy"]
    Clone --> Branch["Create Feature Branch (feat/new-driver)"]
    Branch --> Write["Write Code / Driver Integration"]
    Write --> Unit["Run Unit Tests (Mocked Data)<br/>pytest tests/unit/"]
    Unit --> UnitCheck{"Unit Tests Pass?"}
    UnitCheck -- No --> Debug["Debug & Refactor Code"] --> Write
    UnitCheck -- Yes --> Integ["Run Integration Tests<br/>pytest tests/integration/"]
    Integ --> IntegCheck{"Integration Pass?"}
    IntegCheck -- No --> Debug
    IntegCheck -- Yes --> Tox["Run Tox (Cross-Environment)<br/>tox -e py310,py311,py312"]
    Tox --> ToxCheck{"Tox Fails?"}
    ToxCheck -- Yes --> Debug
    ToxCheck -- No --> Commit["Commit Code (Signed)"]
    Commit --> PR["Open Pull Request (PR) to Main"]
    PR --> CI["GitHub Actions CI Triggered<br/>(Automated Lints & Hardware-Skipped Tests)"]
    CI --> CICheck{"CI Passes & Code Reviewed?"}
    CICheck -- No --> Feedback["Address Review Feedback"] --> Write
    CICheck -- Yes --> Merge["Merge into Main"]
    Merge --> Stop(["stop"])
```""",
}


def hotfix_markdowns(target_dir: str = "Documentation"):
    docs_path = Path(target_dir)
    if not docs_path.exists():
        print(f"Directory {target_dir} not found!")
        return

    md_files = list(docs_path.rglob("*.md"))
    fixed_count = 0

    for file_path in md_files:
        if file_path.name in FIXED_DIAGRAMS:
            try:
                # Opcionális szöveg/magyarázat megtartása
                original_text = file_path.read_text(encoding="utf-8")
                # Csak a diagram blokkot írjuk felül, a fájl elejére
                new_content = FIXED_DIAGRAMS[file_path.name] + "\n\n"

                # Ha volt benne eredeti szöveg a diagram alatt, azt visszatesszük
                if "```" in original_text:
                    parts = original_text.split("```")
                    if len(parts) > 2:
                        new_content += parts[-1].strip()

                file_path.write_text(new_content, encoding="utf-8")
                print(f"[OK] Fixed syntax in: {file_path.name}")
                fixed_count += 1
            except (OSError, UnicodeError) as e:
                # The write failed, or the repaired text contains something the
                # target encoding cannot represent. Both leave the original file
                # untouched and are worth reporting per-file rather than
                # stopping the batch.
                print(f"[ERROR] Could not write {file_path.name}: {e}")

    print(f"\nHotfix Complete! {fixed_count} files successfully repaired.")


if __name__ == "__main__":
    hotfix_markdowns()
