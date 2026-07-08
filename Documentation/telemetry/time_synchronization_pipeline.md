sequenceDiagram
    participant Engine as TelemetryEngine
    participant XR as OpenXR Backend
    participant Compositor as Active VR Compositor
    participant Parquet as Time-Series Dataset

    loop Hardware Pacing Cycle
        Engine->>XR: poll_frame()
        
        XR->>Compositor: xrWaitFrame()
        note over Compositor: Waits for next vsync boundary
        Compositor-->>XR: predictedDisplayTime (Nanoseconds)
        
        XR->>Compositor: xrBeginFrame()
        
        XR->>XR: Convert predictedDisplayTime to Float64 Timestamp
        
        XR->>Compositor: xrLocateSpace(predictedDisplayTime)
        note over XR: Fetch HMD Kinematics exactly at display time
        Compositor-->>XR: HMD Pose (X, Y, Z, Q)
        
        XR->>Compositor: xrGetEyeGazes(predictedDisplayTime)
        note over XR: Fetch Biometrics exactly at display time
        Compositor-->>XR: Eye Vectors, Pupillometry
        
        XR->>XR: Construct TelemetryFrame
        XR->>Engine: return frame
        
        XR->>Compositor: xrEndFrame()
        note over XR, Compositor: Since headless, we submit no graphics layers.
        
        Engine->>Parquet: Write row with 'timestamp' column
    end