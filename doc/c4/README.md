# C4 Component Engine C4 Context Container

# C4 Component Engine

```mermaid
C4Component
    title Component Diagram for VRTelemetry Engine

    Container_Boundary(core_engine, "Core Engine (src.core.engine)") {
        Component(engine_cls, "TelemetryEngine", "Python Class", "Orchestrates lifecycle, holds state, spins up threads.")
        Component(sync_cls, "BiometricSynchronizer", "Python Class", "Manages the asyncio.Queue bridging the sync and async threads.")
    }

    Container_Boundary(backends, "Hardware Backends (src.backends)") {
        Component(openxr_be, "OpenXRHeadlessBackend", "Python Class", "Wraps PyOpenXR C-bindings to poll headset state.")
    }

    Container_Boundary(storage, "Storage Components (src.storage)") {
        Component(db_mgr, "DatabaseManager", "Python Class", "Executes SQLite transactions for metadata.")
        Component(pq_writer, "AsyncParquetWriter", "Python Class", "Batches and serializes PyArrow tables to disk.")
    }

    Container_Boundary(utils, "Utilities (src.utils)") {
        Component(hw_mon, "HardwareMonitor", "Python Class", "Polls low-Hz system stats (CPU/RAM).")
    }

    Rel(engine_cls, openxr_be, "Instantiates & polls at 90Hz", "Synchronous Call")
    Rel(engine_cls, sync_cls, "Instantiates & pushes flat frames", "Method Call")
    Rel(engine_cls, db_mgr, "Instantiates & persists subject metadata", "Synchronous Call")
    Rel(engine_cls, hw_mon, "Instantiates & starts polling thread", "Thread Start")
    Rel(engine_cls, pq_writer, "Instantiates", "Object Creation")
    
    Rel(sync_cls, pq_writer, "Passes batched memory structures", "Async Await")
    
    UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="1")
```

---

# C4 Context Container

```mermaid
C4Context
    title System Context & Container Diagram for VRTelemetry

    Person(researcher, "VR Researcher", "Configures experiments, enforces GDPR consent, and analyzes biometric data.")
    
    System_Boundary(vr_telemetry_sys, "VRTelemetry Framework") {
        Container(cli_bootstrapper, "CLI Orchestrator", "Python", "Parses arguments, enforces GDPR constraints, and initializes the engine (main.py)")
        Container(telemetry_engine, "Telemetry Engine", "Python", "Orchestrates hardware polling, threading, and data synchronization (engine.py)")
        Container(storage_manager, "Storage Subsystem", "Python/PyArrow", "Asynchronously writes float32 tensors to Parquet and metadata to SQLite")
    }

    System_Ext(openxr_runtime, "OpenXR Runtime", "SteamVR / Meta Link / Varjo Base")
    System_Ext(target_vr_app, "Target VR Application", "Unity / Unreal Engine (Running concurrently)")
    System_Ext(dl_pipeline, "Deep Learning Pipeline", "PyTorch / TensorFlow", "Consumes Parquet datasets for cognitive load or cyber-sickness prediction")

    Rel(researcher, cli_bootstrapper, "Starts session with --gdpr-consent & subject ID", "CLI")
    Rel(cli_bootstrapper, telemetry_engine, "Instantiates & Configures")
    Rel(telemetry_engine, openxr_runtime, "Binds XR_MND_headless & polls API", "C-bindings/PyOpenXR")
    Rel(target_vr_app, openxr_runtime, "Renders graphics and consumes main tracking context", "OpenXR API")
    Rel(telemetry_engine, storage_manager, "Pushes 1D TelemetryFrames to ring buffer", "Memory/Queue")
    Rel(storage_manager, dl_pipeline, "Outputs vr_telemetry_[ID].parquet & SQLite", "File System")
    
    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
c4/
├── README.md
├── c4_component_engine.svg
└── c4_context_container.svg
```