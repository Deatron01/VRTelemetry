```mermaid
classDiagram
    class IEyeTrackingDriver {
        <<interface>>
    }
    class EXTEyeGazeDriver
    class FBEyeTrackingSocialDriver
    class HTCEyeTrackingDriver
    class EyeTrackingFactory

    IEyeTrackingDriver <|.. EXTEyeGazeDriver
    IEyeTrackingDriver <|.. FBEyeTrackingSocialDriver
    IEyeTrackingDriver <|.. HTCEyeTrackingDriver
    EyeTrackingFactory --> IEyeTrackingDriver : creates
```
