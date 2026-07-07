# src/core/engine.py

import time
import asyncio
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from src.backends.openxr_headless import OpenXRHeadlessBackend
from src.core.synchronizer import BiometricSynchronizer
from src.storage.parquet_writer import AsyncParquetWriter
from src.storage.database_manager import DatabaseManager
from src.utils.hardware_monitor import HardwareMonitor
from src.utils.logger import logger
from src.core.exceptions import GDPRConsentError

class TelemetryEngine:
    """
    Core orchestrator execution context. Governs the primary tracking sequence,
    delegating OpenXR hardware synchronization to the backend and data storage
    to the asynchronous BiometricSynchronizer, effectively guaranteeing zero frame loss.
    """
    
    def __init__(self, output_dir: str = "Sessions", gdpr_consent: bool = False, subject_metadata: Optional[Dict[str, Any]] = None, hardware_metadata: Optional[Dict[str, Any]] = None):
        self.is_running = False
        self.frames_recorded = 0
        self.gdpr_consent = gdpr_consent
        
        # Enforce Requirement 2.50 / 4.3: Crash cleanly on initialization if biometric profiling has no consent
        if not self.gdpr_consent:
            raise GDPRConsentError("CRITICAL: Biometric tracking initialization aborted. Explicit user GDPR consent missing.")
            
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a unique immutable session identity stamp
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.parquet_path = self.output_dir / f"vr_telemetry_{self.session_id}.parquet"
        
        # Component Instantiation
        self.db_manager = DatabaseManager()
        self.hardware = HardwareMonitor()
        self.backend = OpenXRHeadlessBackend()
        
        # Determine base target frequency (usually 90Hz, will be overridden by hardware display predicted time)
        self.writer = AsyncParquetWriter(output_path=self.parquet_path, target_hz=90)
        self.synchronizer = BiometricSynchronizer(writer=self.writer, hardware_monitor=self.hardware)
        
        # Dedicated thread for the Asyncio Event Loop running the disk writer
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None

        # Consolidate dynamic hardware capabilities with static experiment tracking structures
        hw_meta = hardware_metadata or {}
        
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
            },
            "H-VII_Hardware_Capabilities": hw_meta
        }

    def _start_async_loop(self) -> None:
        """Boots a dedicated background thread to isolate async I/O operations from the OpenXR blocking calls."""
        self._async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._async_loop)
        
        self.synchronizer.start(self._async_loop)
        
        try:
            self._async_loop.run_forever()
        except Exception as e:
            logger.error(f"AsyncIO Loop Exception: {e}")
        finally:
            self._async_loop.run_until_complete(self._async_loop.shutdown_asyncgens())
            self._async_loop.close()

    def start(self) -> None:
        """
        Locks context bindings, spins up asynchronous worker threads, and hands over
        thread execution to the OpenXR hardware runtime pacing loop.
        """
        logger.info("Initializing background telemetry engine and OpenXR headless bindings...")
        
        if not self.backend.initialize():
            logger.error("Failed to bind OpenXR Headless session. Terminating execution.")
            return
            
        # Persist static experiment packets to SQL structural tables prior to tracking sequence execution
        self.db_manager.persist_experiment(self.subject_metadata)
        
        self.hardware.start()
        self.writer.start()
        
        # Spin up consumer loop on independent thread
        self._async_thread = threading.Thread(target=self._start_async_loop, daemon=True, name="AsyncConsumerThread")
        self._async_thread.start()
        
        self.is_running = True
        
        try:
            self._loop()
        except KeyboardInterrupt:
            logger.warning("Telemetry capture sequence interrupted manually by operator.")
        except GDPRConsentError as e:
            logger.error(f"Compliance violation terminated tracking: {e}")
        finally:
            self._teardown()

    def _loop(self) -> None:
        """
        Hardware-synchronized polling cycle. Blocks inherently on xrWaitFrame executed 
        inside the backend. Eliminates time.sleep() jitter and software clock drift.
        """
        logger.info("Main telemetry cycle initiated. Pacing controlled by OpenXR runtime.")
        
        while self.is_running:
            # Secondary runtime check ensuring biometric compliance continuity (Requirement 2.50)
            if not self.gdpr_consent:
                raise GDPRConsentError("CRITICAL: Consent revoked during active sampling window.")

            # Blocking call: wait_frame governs pace. Zero software-side spinning required.
            frame_data = self.backend.poll_frame(self.frames_recorded)
            
            # Simulated environment contextual marker injection (Category 7 values)
            frame_data.scene_id = 2.0
            
            # Push to the decoupled Ring Buffer (BiometricSynchronizer)
            self.synchronizer.push_frame(frame_data)
            self.frames_recorded += 1

    def _teardown(self) -> None:
        """
        Guarantees safe unbinding of hardware API layers and memory-aligned buffer flushes.
        """
        logger.info("Executing safe teardown procedures...")
        self.is_running = False
        
        self.synchronizer.stop()
        if self._async_loop and self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
            
        if self._async_thread:
            self._async_thread.join(timeout=3.0)
            
        self.hardware.stop()
        self.writer.stop()
        self.backend.shutdown()
        
        logger.info(f"Operational log finalized. Valid frames pushed to processing buffer: {self.frames_recorded}")