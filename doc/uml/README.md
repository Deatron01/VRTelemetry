# Base Driver Uml Central Data Schema Er Core Class Diagram Eye Tracking Driver Hierarchy Eye Tracking Driver Uml Ivr Backend Interface Vr Telemetry Exceptions

# Base Driver Uml

```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<abstract>>
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance: xr.Instance, session: xr.Session, app_space: xr.Space) bool
        +populate_frame(frame: TelemetryFrame, timestamp_ns: int) void
        +shutdown() void
    }
```

---

# Central Data Schema Er

```mermaid
erDiagram
    uploaded_sessions {
        TEXT upload_id PK
        TEXT session_id
        TEXT license_id
        TEXT activation_id
        TEXT machine_label
        TEXT subject_id
        TEXT original_filename
        TEXT storage_path
        INTEGER file_size_bytes
        TEXT sha256_checksum
        INTEGER total_frames
        REAL duration_sec
        TEXT metadata_json
        TIMESTAMP received_at
        INTEGER verified
    }

    upload_events {
        INTEGER event_id PK
        TEXT upload_id FK
        TEXT activation_id FK
        TEXT event_type
        TEXT detail
        TEXT ip_address
        TIMESTAMP created_at
    }

    session_logs {
        TEXT log_id PK
        TEXT session_id
        TEXT license_id
        TEXT activation_id
        TEXT storage_path
        INTEGER file_size_bytes
        TIMESTAMP received_at
    }

    uploaded_sessions ||--o{ upload_events : "logs audit events"
```

---

# Core Class Diagram

```mermaid
classDiagram
    class IVRBackend {
        <<interface>>
        +initialize() bool*
        +poll_frame(frame_index: int) TelemetryFrame*
        +shutdown() None*
    }

    class OpenXRHeadlessBackend {
        +initialize() bool
        +poll_frame(frame_index: int) TelemetryFrame
        +shutdown() None
    }

    class TelemetryEngine {
        -is_running : bool
        -frames_recorded : int
        -gdpr_consent : bool
        -session_id : str
        -subject_metadata : dict
        -_async_loop : AbstractEventLoop
        -_async_thread : Thread
        +__init__(output_dir, gdpr_consent, subject_metadata, hardware_metadata)
        +start() None
        -_start_async_loop() None
        -_loop() None
        -_teardown() None
    }

    class TelemetryFrame {
        <<dataclass>>
        +frame_index : int
        +timestamp : float
        +scene_id : float
        +... (Biometric & Kinematic Floats)
    }

    class GDPRConsentError {
        <<Exception>>
    }

    IVRBackend <|-- OpenXRHeadlessBackend : implements
    TelemetryEngine *-- OpenXRHeadlessBackend : owns
    TelemetryEngine ..> GDPRConsentError : throws
    OpenXRHeadlessBackend ..> TelemetryFrame : instantiates
```

---

# Eye Tracking Driver Hierarchy

```mermaid
classDiagram
    class EyeTrackingFactory {
        <<Singleton>>
        +bind_driver(capabilities: dict) IBaseEyeDriver
    }

    class IBaseEyeDriver {
        <<interface>>
        +initialize_extension() bool*
        +poll_gaze() GazeVector*
        +poll_pupillometry() PupillometryData*
    }

    class OpenXREyeGazeExtension {
        -xr_space: XrSpace
        -extension_name: "XR_EXT_eye_gaze_interaction"
        +initialize_extension() bool
        +poll_gaze() GazeVector
        +poll_pupillometry() PupillometryData
    }

    class HTCFacialTracker {
        -sranipal_ctx: Object
        -extension_name: "XR_HTC_facial_tracking"
        +initialize_extension() bool
        +poll_gaze() GazeVector
        +poll_pupillometry() PupillometryData
    }

    class MetaQuestProFace {
        -fb_social_ctx: Object
        -extension_name: "XR_FB_social_tracking"
        +initialize_extension() bool
        +poll_gaze() GazeVector
        +poll_pupillometry() PupillometryData
    }

    class GazeVector {
        <<dataclass>>
        +left_gaze: Vector3
        +right_gaze: Vector3
        +combined_gaze: Vector3
    }
    
    class PupillometryData {
        <<dataclass>>
        +left_dilation_mm: float
        +right_dilation_mm: float
    }

    EyeTrackingFactory ..> IBaseEyeDriver : Instantiates
    IBaseEyeDriver <|-- OpenXREyeGazeExtension : Implements
    IBaseEyeDriver <|-- HTCFacialTracker : Implements
    IBaseEyeDriver <|-- MetaQuestProFace : Implements
    IBaseEyeDriver ..> GazeVector : Returns
    IBaseEyeDriver ..> PupillometryData : Returns
```

---

# Eye Tracking Driver Uml

```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<interface>>
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance: xr.Instance, session: xr.Session, app_space: xr.Space) bool
        +populate_frame(frame: TelemetryFrame, timestamp_ns: int) void
        +shutdown() void
    }
```

---

# Ivr Backend Interface

```mermaid
classDiagram
    class IVRBackend {
        <<abstract>>
        +initialize() bool
        +poll_frame(frame_index: int) TelemetryFrame
        +shutdown() None
    }
    class TelemetryFrame {
    }
    IVRBackend ..> TelemetryFrame : produces
```

---

# Vr Telemetry Exceptions

```mermaid
classDiagram
    Exception <|-- VRTelemetryError
    VRTelemetryError <|-- GDPRConsentError
    VRTelemetryError <|-- HardwareBindingError
    VRTelemetryError <|-- SynchronizationError

    class Exception{
    }
    class VRTelemetryError{
        <<base>>
    }
    class GDPRConsentError{
        +Biometric tracking without consent
    }
    class HardwareBindingError{
        +OpenXR runtime / hardware failure
    }
    class SynchronizationError{
        +Ring buffer exhaustion
    }
```

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
uml/
├── README.md
├── core_class_diagram-1.svg
├── core_class_diagram.svg
└── eye_tracking_driver_hierarchy.svg
```