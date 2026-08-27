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