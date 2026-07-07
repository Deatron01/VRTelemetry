import time
import ctypes
from pathlib import Path
from typing import Dict, Any
from src.backends import discover_active_backend
from src.storage.parquet_writer import AsyncParquetWriter
from src.storage.database_manager import DatabaseManager
from src.utils.hardware_monitor import HardwareMonitor
from src.utils.logger import logger
from src.core.exceptions import GDPRConsentError, HardwareBindingError

try:
    winmm = ctypes.windll.winmm
except AttributeError:
    raise EnvironmentError("OS Kernel Platform Conflict: VRTelemetry requires a Windows host environment.")

class TelemetryEngine:
    """
    Core orchestrator loop execution context. Governs timing precision down to
    sub-millisecond limits to support stable time-series matrix generation.
    """
    def __init__(self, target_hz: int = 90, output_dir: str = "Sessions", gdpr_consent: bool = False, subject_metadata: Dict[str, Any] = None):
        self.target_hz = target_hz
        self.ideal_dt = 1.0 / target_hz
        self.is_running = False
        self.frames_recorded = 0
        self.gdpr_consent = gdpr_consent
        
        # Enforce Requirement 2.50 / 4.3: Crash cleanly on initialization if biometric profiling has no consent
        if not self.gdpr_consent:
            raise GDPRConsentError("CRITICAL: Biometric tracking initialization aborted. Explicit user GDPR consent missing.")
            
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        
        self.parquet_path = self.output_dir / f"vr_telemetry_{self.session_id}.parquet"
        self.writer = AsyncParquetWriter(output_path=self.parquet_path, target_hz=target_hz)
        self.db_manager = DatabaseManager()
        self.hardware = HardwareMonitor()
        self.backend = None
        
        # Default static configuration metadata template mapping setup
        self.subject_metadata = subject_metadata or {
            "M-IV_Static_Metadata": {
                "session_id": self.session_id,
                "subject_id": "SUB_UNKN_01",
                "subject_age": 24,
                "subject_biological_sex": "Male",
                "subject_height_cm": 184.0,
                "subject_weight_kg": 115.0,
                "subject_vr_exp": "Pro",
                "subject_ipd_mm": 64.0
            },
            "C-V_Calibration": {
                "dominant_hand": "Right"
            },
            "Q-VI_Subjective_Labels": {
                "ssq_nausea_score": 0.0,
                "ssq_oculomotor_score": 0.0,
                "nasa_tlx_mental": 20.0,
                "nasa_tlx_physical": 10.0,
                "session_rating": 5
            }
        }

    def start(self) -> None:
        logger.info("Initializing system context structures...")
        self.backend = discover_active_backend()
        
        # Persist static experiment packets to SQL structural tables prior to tracking sequence execution
        self.db_manager.persist_experiment(self.subject_metadata)
        
        self.hardware.start()
        self.writer.start()
        self.is_running = True
        
        # Stabilize system clock limits across host scheduling pools
        winmm.timeBeginPeriod(1)
        
        try:
            self._loop()
        except KeyboardInterrupt:
            logger.warning("Execution loop interrupted manually.")
        finally:
            self._teardown()

    def _loop(self) -> None:
        next_frame_time = time.perf_counter()
        while self.is_running:
            # Secondary runtime check ensuring compliance continuity
            if not self.gdpr_consent:
                raise GDPRConsentError("CRITICAL: Consent revoked during active sampling window.")

            frame_data = self.backend.poll_frame(self.frames_recorded)
            
            # Inject low-frequency operational system telemetry updates
            frame_data.cpu_utilization = self.hardware.cpu_usage
            frame_data.voice_amplitude_db = self.hardware.voice_db
            
            # Inject dynamic Category 7 values (Simulated structural environment variables)
            frame_data.scene_id = 2.0  # actively moving inside Testpálya context
            
            self.writer.push(frame_data)
            self.frames_recorded += 1
            next_frame_time += self.ideal_dt
            
            # Hybrid Sleep/Spin Execution Strategy
            now = time.perf_counter()
            time_to_sleep = next_frame_time - now
            if time_to_sleep > 0.002:
                time.sleep(time_to_sleep - 0.002)
            while time.perf_counter() < next_frame_time:
                pass

    def _teardown(self) -> None:
        self.is_running = False
        winmm.timeEndPeriod(1)
        self.hardware.stop()
        self.writer.stop()
        if self.backend:
            self.backend.shutdown()
        logger.info(f"Operational log finalized. Frames output safely to disk: {self.frames_recorded}")