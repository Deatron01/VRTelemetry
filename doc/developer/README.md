# Ci Cd Execution Matrix Contribution Workflow Quick Reference Mindmap

# Ci Cd Execution Matrix

```mermaid
flowchart LR
    Commit["Push / PR to Main"] --> GH_Actions["GitHub Actions Runner"]
    GH_Actions --> Linting["Flake8 / Black Linter"]
    Linting --> Matrix{"OS & Python Matrix"}
    Matrix --> Win310["Windows - Python 3.10"]
    Matrix --> Win311["Windows - Python 3.11"]
    Matrix --> Win312["Windows - Python 3.12"]
    Matrix --> Lin311["Ubuntu - Python 3.11<br/>(Logic Only)"]
    Win310 --> ToxRun["Run Tox: -m 'not hardware'"]
    Win311 --> ToxRun
    Win312 --> ToxRun
    Lin311 --> ToxRun
    ToxRun --> Aggregate["Aggregate Pytest Coverage"]
    Aggregate --> Status{"Coverage > 85%?"}
    Status -- Yes --> Merge["Allow PR Merge"]
    Status -- No --> Block["Block PR Merge"]
    classDef pipeline fill:#cfd8dc,stroke:#607d8b,stroke-width:2px;
    classDef success fill:#c8e6c9,stroke:#4caf50,stroke-width:2px;
    classDef fail fill:#ffcdd2,stroke:#f44336,stroke-width:2px;
    class Linting,Matrix,ToxRun,Aggregate pipeline;
    class Merge success;
    class Block fail;
```

---

# Contribution Workflow

```mermaid
flowchart TD
    Start(["Start"]) --> Fork["Fork VRTelemetry Repository"]
    Fork --> Clone["Clone Local Copy"]
    Clone --> Branch["Create Feature Branch (feat/new-driver)"]
    Branch --> Write["Write Code / Driver Integration"]
    Write --> Unit["Run Unit Tests (Mocked Data)<br/>pytest tests/unit/"]
    Unit --> UnitCheck{"Unit Tests Pass?"}
    UnitCheck -- No --> Debug["Debug & Refactor Code"] --> Write
    UnitCheck -- Yes --> Integ["Run Integration Tests<br/>pytest tests/integration/"]
    Integ --> IntegCheck{"Integration Pass?"}
    IntegCheck -- No --> Debug
    IntegCheck -- Yes --> Tox["Run Tox (Cross-Environment)<br/>tox -e py310,py311,py312"]
    Tox --> ToxCheck{"Tox Fails?"}
    ToxCheck -- Yes --> Debug
    ToxCheck -- No --> Commit["Commit Code (Signed)"]
    Commit --> PR["Open Pull Request (PR) to Main"]
    PR --> CI["GitHub Actions CI Triggered<br/>(Automated Lints & Hardware-Skipped Tests)"]
    CI --> CICheck{"CI Passes & Code Reviewed?"}
    CICheck -- No --> Feedback["Address Review Feedback"] --> Write
    CICheck -- Yes --> Merge["Merge into Main"]
    Merge --> Stop(["stop"])
```

---

# Quick Reference Mindmap

```mermaid
mindmap
  root((VRTelemetry))
    Core Tenets
      Zero Frame Drops
        Async I/O Threads
        Non-Blocking Ring Buffer
      Zero Interference
        XR_MND_headless
        No Swapchains
      AI Ready Output
        1D Float32 Arrays
        Apache Parquet Storage
    Privacy & Compliance
      GDPR Enforcement
        Strict CLI Gates
        Runtime Revocation Checks
      Anonymization
        Subject UUIDs
        Local Disk Storage Only
    Data Types
      Metadata
        SQLite Schema
        M-IV Static Traits
        Q-VI Surveys
      Time-Series
        90Hz-120Hz Hardware Polling
        Eye Vectors & Kinematics
    Backends
      OpenXR API Wrappers
      EyeTrackingFactory
        Vendor Polymorphism
```

---

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
developer/
├── README.md
├── ci_cd_execution_matrix.svg
├── contribution_workflow.svg
└── quick_reference_mindmap.svg
```