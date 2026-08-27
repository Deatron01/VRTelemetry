# Metadata Hierarchy

```mermaid
classDiagram
    class CLIArguments {
        <<argparse.Namespace>>
        +gdpr_consent: bool
        +output: str
        +subject_id: str
    }

    class TelemetryEngineContext {
        +session_id: str (Generated)
        +subject_metadata: Dictionary
    }

    class SubjectMetadata {
        <<Dictionary>>
    }

    class M_IV_Static_Metadata {
        +session_id: str
        +subject_id: str (Injected from CLI)
        +subject_age: int
        +subject_biological_sex: str
        +subject_height_cm: float
        +subject_weight_kg: float
        +subject_vr_exp: str
        +subject_ipd_mm: float
    }

    class C_V_Calibration {
        +dominant_hand: str
    }

    class Q_VI_Subjective_Labels {
        +ssq_nausea_score: float
        +ssq_oculomotor_score: float
        +nasa_tlx_mental: float
        +nasa_tlx_physical: float
        +session_rating: int
    }

    class H_VII_Hardware_Capabilities {
        +openxr_runtime: str (Injected from Discovery)
        +hmd_model: str (Injected from Discovery)
        +has_eye_tracking: bool (Injected from Discovery)
    }

    CLIArguments --> TelemetryEngineContext : Configures via Bootstrapper
    TelemetryEngineContext *-- SubjectMetadata : Initializes
    SubjectMetadata *-- M_IV_Static_Metadata : Contains Category 4
    SubjectMetadata *-- C_V_Calibration : Contains Category 5
    SubjectMetadata *-- Q_VI_Subjective_Labels : Contains Category 6
    SubjectMetadata *-- H_VII_Hardware_Capabilities : Contains Category 7
```

---

# Postcss Config

```mermaid
graph TD
    A[postcss.config.js] --> B[tailwindcss]
    A --> C[autoprefixer]
```

---

# Postcss Config Architecture

```mermaid
graph TD
    A[Source CSS] --> B[PostCSS Processor]
    B --> C[Tailwind CSS Plugin]
    B --> D[Autoprefixer Plugin]
    C --> E[Processed CSS Output]
    D --> E
```

---

# Tailwind Config

```mermaid
graph TD
    A[tailwind.config.js] -->|Consumes tokens| B[Tailwind CSS Compiler]
    B -->|Generates utility classes| C[React Components]
```

---

# Tailwind Configuration

```mermaid
graph TD
    A[Tailwind Config] --> B[Content Paths]
    A --> C[Theme Extensions]
    C --> D[Colors: Research Palette]
    C --> E[Box Shadow: Glass]
    C --> F[Font Family: Sans & Mono]
```

---

# Vite Config

```mermaid
graph TD
    A[vite.config.ts] -->|Uses| B[defineConfig]
    A -->|Includes| C[react plugin]
    C -->|Transforms| D[React JSX & TSX Code]
```

---

# Vite Configuration Diagram

```mermaid
graph TD
    A[vite.config.ts] -->|Loads| B(Vite defineConfig)
    B -->|Uses Plugin| C(@vitejs/plugin-react)
    C -->|Enables| D[React JSX & Fast Refresh]
```

---
