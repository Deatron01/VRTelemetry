flowchart LR
    %% Hardware Sources (Via OpenXR)
    subgraph OpenXR_Runtime ["OpenXR DisplayTime Frame"]
        HMD[HMD Pose (LocateSpace)]
        EyeGaze[Eye Gazes (XR_EXT_eye_gaze_interaction)]
        Pupil[Pupillometry (Vendor Extension)]
    end

    %% Extraction & Flattening
    subgraph TelemetryFrame_Construction ["TelemetryFrame (1D Flat Array)"]
        direction TB
        
        T_Timestamp["[0] timestamp: float64"]
        
        T_HMD["[1-7] hmd_pos_x, y, z <br/> hmd_rot_x, y, z, w"]
        
        T_Gaze["[8-13] left_gaze_x, y, z <br/> right_gaze_x, y, z"]
        
        T_Pupil["[14-15] pupil_dilation_left, right"]
    end

    %% Mappings
    HMD -->|Extract Position (Vector3) <br/> & Orientation (Quaternion)| T_HMD
    EyeGaze -->|Extract Left & Right <br/> Direction Vectors (Vector3)| T_Gaze
    Pupil -->|Extract Floats (mm)| T_Pupil
    
    %% Output
    T_Timestamp --> ParquetRow
    T_HMD --> ParquetRow
    T_Gaze --> ParquetRow
    T_Pupil --> ParquetRow
    
    ParquetRow[(Appended to PyArrow Batch)]
    
    classDef runtime fill:#cfd8dc,stroke:#607d8b,stroke-width:2px;
    classDef frame fill:#e1bee7,stroke:#8e24aa,stroke-width:2px;
    class HMD,EyeGaze,Pupil runtime;
    class T_Timestamp,T_HMD,T_Gaze,T_Pupil frame;