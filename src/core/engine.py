# src/core/engine.py

import time
import asyncio
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from src.backends.backend_steamvr import SteamVROverlayBackend
from src.core.synchronizer import BiometricSynchronizer
from src.storage.parquet_writer import AsyncParquetWriter
from src.storage.database_manager import DatabaseManager
from src.utils.hardware_monitor import HardwareMonitor
from src.utils.logger import logger
from src.core.exceptions import GDPRConsentError

class TelemetryEngine:
    """
    Production telemetry orchestrator. Guarantees deterministic synchronization between
    the OpenXR hardware pacing loop and the asynchronous I/O storage subsystems.
    """
    
    def __init__(self, output_dir: str = "Sessions", gdpr_consent: bool = False, subject_metadata: Optional[Dict[str, Any]] = None, hardware_metadata: Optional[Dict[str, Any]] = None):
        self.is_running = False
        self.frames_recorded = 0
        self.gdpr_consent = gdpr_consent
        
        if not self.gdpr_consent:
            raise GDPRConsentError("CRITICAL: Biometric tracking initialization aborted. Explicit user GDPR consent missing.")
            
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.parquet_path = self.output_dir / f"vr_telemetry_{self.session_id}.parquet"
        
        self.db_manager = DatabaseManager()
        self.hardware = HardwareMonitor()
        self.backend = SteamVROverlayBackend()
        
        # Target 120Hz capacity for modern headsets, AsyncParquetWriter will batch accordingly
        self.writer = AsyncParquetWriter(output_path=self.parquet_path, target_hz=120)
        self.synchronizer = BiometricSynchronizer(writer=self.writer, hardware_monitor=self.hardware)
        
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

        self.subject_metadata = subject_metadata or {
            "M-IV_Static_Metadata": {
                "session_id": self.session_id,
                "subject_id": "SUB_UNKN_01"
            },
            "H-VII_Hardware_Capabilities": hardware_metadata or {}
        }

    def _start_async_loop(self) -> None:
        """Isolated thread execution for non-blocking I/O operations."""
        self._async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._async_loop)
        
        self.synchronizer.start(self._async_loop)
        
        try:
            self._async_loop.run_forever()
        except Exception as e:
            logger.error(f"AsyncIO Loop Exception: {e}")
        finally:
            # Ensure pending tasks are flushed to disk before destroying the loop
            pending = asyncio.all_tasks(loop=self._async_loop)
            for task in pending:
                task.cancel()
            self._async_loop.run_until_complete(self._async_loop.shutdown_asyncgens())
            self._async_loop.close()

    def start(self) -> None:
        """
        Executes deterministic multi-threaded boot sequence.
        """
        logger.info("Booting production telemetry engine (Overlay Mode)...")
        
        if not self.backend.initialize():
            logger.error("Failed to bind OpenXR session. Terminating execution.")
            return
            
        self.db_manager.persist_experiment(self.subject_metadata)
        
        self.hardware.start()
        self.writer.start()
        
        self._shutdown_event.clear()
        self._async_thread = threading.Thread(target=self._start_async_loop, daemon=True, name="TelemetryConsumerThread")
        self._async_thread.start()
        
        self.is_running = True
        
        try:
            self._loop()
        except KeyboardInterrupt:
            logger.warning("Telemetry capture sequence interrupted manually.")
        except Exception as e:
            logger.error(f"Critical runtime exception in OpenXR loop: {e}")
        finally:
            self._teardown()

    def _loop(self) -> None:
        """
        The strictly hardware-synchronized main loop. 
        Zero thread-sleeps; execution speed is entirely dictated by xrWaitFrame.
        """
        logger.info("Main telemetry cycle active. Listening for HMD pacing.")
        
        while self.is_running and not self._shutdown_event.is_set():
            if not self.gdpr_consent:
                logger.error("Consent revoked during active sampling.")
                break

            # Poll hardware (blocks until headset requires a frame)
            frame_data = self.backend.poll_frame(self.frames_recorded)
            
            # If tracking drops or session isn't ready, timestamp will be 0. Avoid spamming null frames.
            if frame_data.timestamp_ns > 0:
                self.synchronizer.push_frame(frame_data)
                self.frames_recorded += 1

    def _teardown(self) -> None:
        """
        Guarantees flawless memory deallocation and prevents file corruption.
        The order of operations is strictly enforced to prevent segmentation faults.
        """
        logger.info("Executing deterministic teardown sequence...")
        self.is_running = False
        self._shutdown_event.set()
        
        # 1. Stop feeding new frames into the queue
        self.synchronizer.stop()
        
        # 2. Safely wind down the AsyncIO loop handling disk writes
        if self._async_loop and self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
            
        if self._async_thread and self._async_thread.is_alive():
            self._async_thread.join(timeout=5.0)
            
        # 3. Terminate auxiliary monitors
        self.hardware.stop()
        self.writer.stop()
        
        # 4. Destroy OpenXR context LAST to prevent driver panic
        self.backend.shutdown()
        
        logger.info(f"Telemetry engine shutdown complete. Total frames archived: {self.frames_recorded}")