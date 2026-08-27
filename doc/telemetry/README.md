# Biometric Vector Assembly Eye Tracking Dataflow Eye Tracking Telemetry Flow Openxr Headless Initialization Physiology Dataflow Physiology Telemetry Flow System Profiler Telemetry T Combined

# Biometric Vector Assembly

```mermaid
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
```

---

# Eye Tracking Dataflow

```mermaid
graph TD
    A[useTelemetryStore] -->|frames array| B(EyeTracking Component)
    B -->|useMemo calculation| C[chartData array]
    C -->|renders metrics| D[Metric Summary Cards]
    C -->|renders chart| E[ResponsiveContainer AreaChart]
```

---

# Eye Tracking Telemetry Flow

```mermaid
graph TD
    A[Telemetry Store useTelemetryStore] -->|Fetches frames| B(EyeTracking Component)
    B -->|Computes quaternion delta & sampling| C[Memoized Chart Data]
    C -->|Renders metrics & statistics| D[Summary Panels]
    C -->|Passes data to AreaChart| E[Recharts Responsive Container]
```

---

# Openxr Headless Initialization

```mermaid
sequenceDiagram
    participant Engine as TelemetryEngine
    participant XRBackend as OpenXRHeadlessBackend
    participant OpenXR as OpenXR API (xr)
    participant Display as OS Window Manager

    Engine->>XRBackend: initialize()
    
    XRBackend->>OpenXR: xrEnumerateInstanceExtensionProperties()
    note over OpenXR: Must verify XR_MND_headless is supported
    
    XRBackend->>OpenXR: xrCreateInstance(extensions=["XR_MND_headless", ...])
    OpenXR-->>XRBackend: XrInstance handle
    
    XRBackend->>OpenXR: xrGetSystem(XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY)
    OpenXR-->>XRBackend: XrSystemId
    
    note over XRBackend, Display: CRITICAL DIFFERENCE: No Swapchains or Graphics Binding required!
    
    XRBackend->>OpenXR: xrCreateSession(systemId)
    OpenXR-->>XRBackend: XrSession handle
    
    XRBackend->>OpenXR: xrCreateReferenceSpace(XR_REFERENCE_SPACE_TYPE_STAGE)
    OpenXR-->>XRBackend: XrSpace (Stage/Room-Scale)
    
    XRBackend->>OpenXR: xrCreateActionSet()
    note over OpenXR: Bind Hand Tracking & Gaze Actions
    XRBackend->>OpenXR: xrAttachSessionActionSets()
    
    XRBackend->>OpenXR: xrBeginSession()
    OpenXR-->>XRBackend: XR_SUCCESS
    
    XRBackend-->>Engine: return True
```

---

# Physiology Dataflow

```mermaid
graph TD
    A[useTelemetryStore] -->|Retrieves raw frames| B(Physiology Component)
    B -->|Downsamples & calculates speed| C[chartData Memo]
    C -->|Renders statistics| D[Summary Cards]
    C -->|Feeds dual-axis data| E[Recharts LineChart]
    E -->|Left Y-Axis| F[Heart Rate (BPM)]
    E -->|Right Y-Axis| G[Head Speed (m/s)]
```

---

# Physiology Telemetry Flow

```mermaid
graph TD
    A[useTelemetryStore] -->|Frames Data| B(Physiology Component)
    B -->|Downsample & Calculate Speed| C[chartData Memo]
    C --> D[Summary Statistics Cards]
    C --> E[Recharts LineChart ResponsiveContainer]
```

---

# System Profiler Telemetry

```mermaid
graph TD
    A[collect_system_profile] --> B[OS & Python Info]
    A --> C[psutil Hardware Stats]
    A --> D[_collect_gpu_info]
    D --> E{Platform Check}
    E -->|Windows| F[wmic]
    E -->|Linux| G[lspci]
    E -->|Darwin| H[system_profiler]
    I[collect_runtime_snapshot] --> J[CPU/RAM Load Metrics]
```

---

# Time Synchronization Pipeline

```mermaid
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
```

---

---
