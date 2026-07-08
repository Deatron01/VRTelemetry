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