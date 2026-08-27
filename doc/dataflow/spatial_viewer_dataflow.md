```mermaid
flowchart TD
    Store[useTelemetryStore] -->|Frames & Current Index| VRRig[VRRig Component]
    Store -->|Frames Array| AnalyticalLayers[AnalyticalLayers Component]
    Store -->|Frames Array| LivePoRCursor[LivePoRCursor Component]
    VRRig --> Canvas[React Three Fiber Canvas]
    AnalyticalLayers --> Canvas
    LivePoRCursor --> Canvas
    UI[User Layer Toggles] --> SpatialViewer[SpatialViewer Container]
```
