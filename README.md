# VRTelemetry: Headless Biometric Acquisition Framework

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://python.org)
[![OpenXR](https://img.shields.io/badge/OpenXR-1.0-green.svg)](https://www.khronos.org/openxr/)
[![Data Storage](https://img.shields.io/badge/Storage-Apache%20Parquet-orange.svg)](https://parquet.apache.org/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Compliance](https://img.shields.io/badge/Compliance-GDPR%20Ready-brightgreen.svg)]()

**VRTelemetry** is an enterprise-grade, zero-interference OpenXR telemetry system architected for virtual reality biometric research, cognitive load analysis, and Deep Learning time-series dataset generation. 

By operating entirely in the background via OpenXR API Layers (`XR_MND_headless`), the framework harvests stereoscopic eye vectors, pupil dilations, high-frequency spatial kinematics, and hardware states while external commercial or experimental VR applications remain fully in focus and undisturbed.

---

## 🧠 Core Architectural Features

- **Zero-Interference Background Execution:** Utilizes `XR_MND_headless` to run concurrently with any primary VR application (Unity, Unreal, Custom Engines) without stealing graphics context or rendering resources.
- **Asynchronous Producer-Consumer Topology:** Bypasses Python GIL restrictions via `asyncio` and `threading`, strictly separating high-frequency hardware data acquisition from disk I/O to guarantee **0% frame drops**.
- **Hardware-Locked Pacing:** Relies exclusively on OpenXR's `xrWaitFrame` prediction timers for deterministic, sub-millisecond polling cycles (90Hz - 120Hz), eliminating software sleep jitter.
- **Zero-Copy Flat Tensors:** Data structures map natively to 1D `Float32` primitives and are flushed directly to **Apache Parquet** columnar binaries. This halves VRAM requirements and allows instant ingestion into PyTorch or TensorFlow DataLoader pipelines.
- **Vendor-Agnostic Eye Tracking Factory:** Autonomously detects and binds the highest-fidelity biometric extensions available at runtime (supports HTC Vive Pro Eye, Meta Quest Pro, and generic OpenXR gaze extensions).
- **Strict Biometric Consent Enforcement:** Hard-coded GDPR safety blocks prevent data harvesting without explicit, actively maintained user consent flags.

---

## ⚙️ Installation & Setup

### Prerequisites
* Windows 10/11 (Required for current OpenXR graphics context abstractions).
* Python 3.10, 3.11, or 3.12.
* An active OpenXR-compatible runtime (Meta Quest Link, SteamVR, Vive Console, or Varjo Base).

### Deployment
Clone the repository and run the automated framework bootstrapper, which verifies system compliance and installs all necessary memory-aligned C-extensions (PyArrow, Numpy) and API wrappers (PyOpenXR).

```bash
git clone [https://github.com/Deatron01/VRTelemetry.git](https://github.com/Deatron01/VRTelemetry.git)
cd VRTelemetry
python -m src.tert_runner
```

Alternatively, install dependencies manually:
```bash
pip install -r requirements.txt
```

---

## 🚀 Usage

### 1. Initiating a Telemetry Session
To capture biometric data safely alongside your target VR applications, initiate the runner. The framework will **hard-abort** unless subject consent is explicitly passed via the CLI.

```bash
python -m src.main --gdpr-consent --subject-id "SUB_001_ALPHA" --output "./Sessions"
```

* **`--gdpr-consent`**: (Required) Acknowledges explicit biometric collection consent.
* **`--subject-id`**: (Optional) Anonymized UUID for the active participant. Defaults to `SUB_UNKN_01`.
* **`--output`**: (Optional) Target directory for Parquet matrices and SQLite relational metadata.

### 2. Inspecting the Acquired Data
Verify the integrity, float32 compliance, and frame validity of your recorded sessions instantly using the built-in diagnostic tool.

```bash
python read_data.py Sessions/vr_telemetry_20260626_130232.parquet
```

### 3. Deep Learning Pre-Processing
Before feeding the telemetry into predictive models (e.g., RNNs or LSTMs for cyber-sickness prediction or cognitive load classification), run the AI post-processor. This pipeline executes exponential moving average smoothing, forward-fill validation for sensor dropouts, and Z-Score standardization.

```python
from src.storage.ai_preprocessor import AIPostProcessor

processor = AIPostProcessor(input_parquet_path="Sessions/vr_telemetry_20260626_130232.parquet")
processor.process()
# Outputs: Sessions/vr_telemetry_20260626_130232_ai_ready.parquet
```

---

## 📂 Project Structure

```text
VRTelemetry/
├── src/
│   ├── main.py                     # CLI Orchestrator and Bootstrapper
│   ├── tert_runner.py              # Environment Validation Entrypoint
│   ├── core/                       # 1D Tensors, Sync Queues, Orchestration Loop
│   ├── backends/                   # Headless OpenXR HAL & Capability Discovery
│   ├── eye_tracking/               # Polymorphic Biometric Extension Drivers
│   ├── storage/                    # Async Parquet Writer & SQLite Schema Managers
│   └── utils/                      # Thread-Safe Logging & Low-Hz System Polling
├── tests/
│   ├── integration/                # End-to-End Pipeline Validation
│   ├── performance/                # 10,000-Frame Zero-Loss Stress Tests
│   └── unit/                       # Component Isolation Testing
├── requirements.txt
├── pytest.ini
└── tox.ini
```

---

## 🛡️ Privacy & GDPR Compliance

This framework is built for human-subject scientific research. It handles highly sensitive biometric data, including real-time pupillometry, stereoscopic convergence, and micro-movements. 
* **Data Isolation:** No data is transmitted externally. All Parquet matrices and SQLite ledgers are stored strictly on the local disk.
* **Consent Gates:** The `TelemetryEngine` features runtime checks verifying the `--gdpr-consent` flag at both instantiation and iteratively during the hardware loop.
* **Anonymization:** UUIDs are utilized in place of personally identifiable information.

---

## 🧪 Testing

The repository uses `pytest` for unit and integration testing, and `tox` for cross-environment verification.

Run the standard test suite:
```bash
pytest tests/
```

To run tests without requiring an active VR headset connected to the host machine:
```bash
pytest tests/ -m "not hardware"
```