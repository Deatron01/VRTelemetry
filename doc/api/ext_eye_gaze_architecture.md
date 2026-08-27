```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<interface>>
        +get_extension_name() str
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns) void
        +shutdown() void
    }
    class EXTEyeGazeDriver {
        -session: xr.Session
        -app_space: xr.Space
        -action_set: xr.ActionSet
        -eye_gaze_action: xr.Action
        -eye_space: xr.Space
        +get_extension_name() str
        +get_additional_extensions() List[str]
        +get_priority() int
        +initialize(instance, session, app_space) bool
        +populate_frame(frame, timestamp_ns) void
        +shutdown() void
    }
    IEyeTrackingDriver <|-- EXTEyeGazeDriver
```