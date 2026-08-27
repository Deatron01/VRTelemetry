```mermaid
graph TD;
    A[useTelemetryStore] -->|Frames & Indices| B(VRRig)
    A -->|Frames & Indices| C(LivePoRCursor)
    A -->|Frames & Indices| D(AnalyticalLayers)
    B --> E[Three.js Canvas]
    C --> E
    D --> E
    F[User Controls] -->|Toggle Layers| E
```