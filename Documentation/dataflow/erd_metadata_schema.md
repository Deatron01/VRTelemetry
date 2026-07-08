erDiagram
    %% SQLite Relational Data
    EXPERIMENT_SESSION ||--|| M_IV_STATIC_METADATA : contains
    EXPERIMENT_SESSION ||--|| C_V_CALIBRATION : configures
    EXPERIMENT_SESSION ||--|| Q_VI_SUBJECTIVE_LABELS : evaluated_by
    EXPERIMENT_SESSION ||--|| H_VII_HARDWARE_CAPABILITIES : executed_on
    
    %% Implicit relation to Parquet
    EXPERIMENT_SESSION ||--o{ PARQUET_TIME_SERIES : "Session ID Match"

    EXPERIMENT_SESSION {
        string session_id PK "Primary Key (e.g., 20260626_130232)"
        timestamp created_at
        boolean gdpr_consent_verified
    }

    M_IV_STATIC_METADATA {
        string subject_id "Anonymized UUID"
        int subject_age
        string subject_biological_sex
        float subject_height_cm
        float subject_weight_kg
        string subject_vr_exp "None/Beginner/Pro"
        float subject_ipd_mm "Inter-pupillary distance"
    }

    C_V_CALIBRATION {
        string dominant_hand "Left/Right/Ambi"
    }

    Q_VI_SUBJECTIVE_LABELS {
        float ssq_nausea_score "Simulator Sickness Questionnaire"
        float ssq_oculomotor_score
        float nasa_tlx_mental "Cognitive Load Estimate"
        float nasa_tlx_physical
        int session_rating "1-10 Scale"
    }

    H_VII_HARDWARE_CAPABILITIES {
        string openxr_runtime "e.g., SteamVR, Oculus"
        string hmd_model "e.g., Quest Pro, Index"
        boolean has_eye_tracking
    }

    %% Apache Parquet Columnar Data
    PARQUET_TIME_SERIES {
        int frame_index "Sequential Monotonic ID"
        float timestamp "High-Res Hardware Timer"
        float scene_id "Contextual Label"
        float eye_gaze_dir_x "Vector X"
        float eye_gaze_dir_y "Vector Y"
        float eye_gaze_dir_z "Vector Z"
        float pupil_dilation_left "Millimeters"
        float pupil_dilation_right "Millimeters"
        float hmd_pos_x "Kinematics X"
        float hmd_pos_y "Kinematics Y"
        float hmd_pos_z "Kinematics Z"
    }