classDiagram
    class ParquetTimeSeriesDataset {
        <<Apache Parquet Columnar Schema>>
        +frame_index : Int64
        +timestamp : Float64
        +scene_id : Float32
        +hmd_pos_x : Float32
        +hmd_pos_y : Float32
        +hmd_pos_z : Float32
        +hmd_rot_x : Float32
        +hmd_rot_y : Float32
        +hmd_rot_z : Float32
        +hmd_rot_w : Float32
        +left_gaze_dir_x : Float32
        +left_gaze_dir_y : Float32
        +left_gaze_dir_z : Float32
        +right_gaze_dir_x : Float32
        +right_gaze_dir_y : Float32
        +right_gaze_dir_z : Float32
        +pupil_dilation_left : Float32
        +pupil_dilation_right : Float32
        +cpu_utilization_pct : Float32
        +ram_utilization_mb : Float32
    }
    
    note for ParquetTimeSeriesDataset "All Biometric and Kinematic values \nare cast to Float32 to optimize \nVRAM usage during PyTorch ingestion."
    
    class Units_and_Space {
        <<Coordinate & Measurement Standards>>
        - Coordinate System: Right-Handed Y-Up (OpenXR Standard)
        - Positions (pos_*): Meters (m)
        - Rotations (rot_*): Quaternions (Normalized)
        - Directions (dir_*): Unit Vectors
        - Pupillometry: Millimeters (mm)
        - Timestamp: Nanoseconds since VR Compositor Boot
    }
    
    ParquetTimeSeriesDataset .. Units_and_Space : Adheres To