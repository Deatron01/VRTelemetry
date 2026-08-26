# src/core/engine.py
import time
import asyncio
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from src.backends.udp_receiver import NativeQuestReceiver
from src.backends.backend_steamvr import SteamVROverlayBackend
from src.backends.backend_openxr import OpenXRBackend
from src.backends.backend_ocolus import OculusBackend
from src.backends.openxr_headless import OpenXRHeadlessBackend

from src.core.synchronizer import BiometricSynchronizer
from src.storage.parquet_writer import AsyncParquetWriter
from src.storage.database_manager import DatabaseManager
from src.utils.hardware_monitor import HardwareMonitor
from src.utils.logger import logger
from src.core.exceptions import GDPRConsentError

from src.storage.session_uploader import SessionUploader
from src.license_service.local_cache import LocalLicenseCache

from src.utils.system_profiler import collect_system_profile

class TelemetryEngine:
    """
    Production telemetry orchestrator. Guarantees deterministic synchronization between
    the OpenXR hardware pacing loop (or UDP sockets) and the asynchronous I/O storage subsystems.
    """
    
    def __init__(self, output_dir: str = "Sessions", gdpr_consent: bool = False,
                 subject_metadata: Optional[Dict[str, Any]] = None,
                 hardware_metadata: Optional[Dict[str, Any]] = None,
                 central_server_url: str = "http://192.168.1.X:9000"):
        self.is_running = False
        self.frames_recorded = 0
        self.gdpr_consent = gdpr_consent
        
        self.local_license_cache = LocalLicenseCache()
        self.uploader = SessionUploader(central_server_url, self.local_license_cache)
        
        if not self.gdpr_consent:
            raise GDPRConsentError("CRITICAL: Biometric tracking initialization aborted. Explicit user GDPR consent missing.")
            
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.parquet_path = self.output_dir / f"vr_telemetry_{self.session_id}.parquet"
        
        self.db_manager = DatabaseManager()
        self.hardware = HardwareMonitor()
        
        self.backend = None
        
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
        asyncio.set_event_loop(self._async_loop)
        
        self.synchronizer.start(self._async_loop)
        
        try:
            self._async_loop.run_forever()
        except Exception as e:
            logger.error(f"AsyncIO Loop Exception: {e}")
        finally:
            pending = asyncio.all_tasks(loop=self._async_loop)
            for task in pending:
                task.cancel()
            self._async_loop.run_until_complete(self._async_loop.shutdown_asyncgens())
            self._async_loop.close()

    def start(self) -> None:
        """
        Executes deterministic multi-threaded boot sequence and branches 
        to the appropriate hardware tracking backend.
        """
        logger.info("Booting production telemetry engine...")
        
        self.db_manager.persist_experiment(self.subject_metadata)
        self.hardware.start()
        self.writer.start()
        
        # Sweep anything left over from a prior offline session before starting new work.
        # Non-blocking in spirit — a slow/unreachable server here just logs and moves on,
        # it must never delay the actual telemetry loop from starting.
        try:
            retry_result = self.uploader.retry_pending()
            if retry_result["attempted"]:
                logger.info(f"Retried {retry_result['attempted']} pending upload(s) from previous sessions, "
                            f"{retry_result['succeeded']} succeeded.")
        except Exception as e:
            logger.warning(f"Pending upload retry sweep failed (will retry next start): {e}")
            
        self._shutdown_event.clear()
        self._async_loop = asyncio.new_event_loop() 
        
        self._async_thread = threading.Thread(target=self._start_async_loop, daemon=True, name="TelemetryConsumerThread")
        self._async_thread.start()
        
        self.is_running = True
        backend_mode = getattr(self, "configured_backend", "auto")
        
        try:
            if backend_mode == "quest_udp":
                self._run_quest_udp_mode()
            else:
                if backend_mode == "openxr":
                    self.backend = OpenXRBackend()
                elif backend_mode == "oculus":
                    self.backend = OculusBackend()
                else: # "auto" vagy "steamvr" esetén
                    self.backend = SteamVROverlayBackend()
                    
                self._run_pcvr_mode()
                
        except KeyboardInterrupt:
            logger.warning("Telemetry capture sequence interrupted manually.")
        except Exception as e:
            logger.error(f"Critical runtime exception in main loop: {e}")
        finally:
            self._teardown()

    def _run_pcvr_mode(self) -> None:
        """Standard PCVR hardware-synchronized loop via dynamically selected API."""
        # Frissített log szöveg, hogy alkalmazkodjon az aktív backendhez
        logger.info(f"Initializing Native Context via {self.backend.__class__.__name__}...")
        if not self.backend.initialize():
            logger.error("Failed to bind PCVR session. Terminating execution.")
            return

        logger.info("Main telemetry cycle active. Listening for HMD pacing.")
        while self.is_running and not self._shutdown_event.is_set():
            if not self.gdpr_consent:
                logger.error("Consent revoked during active sampling.")
                break

            # Poll hardware (blocks until headset requires a frame)
            frame_data = self.backend.poll_frame(self.frames_recorded)
            
            if frame_data.timestamp_ns > 0:
                self.synchronizer.push_frame(frame_data)
                self.frames_recorded += 1

    def _run_quest_udp_mode(self) -> None:
        """Headless network loop catching native Quest Pro biometric payloads."""
        port = getattr(self, "network_port", 5005)
        logger.info(f"Bypassing PCVR Runtimes. Booting Native UDP Receiver on port {port}...")
        
        receiver = NativeQuestReceiver(host="0.0.0.0", port=port)
        
        future = asyncio.run_coroutine_threadsafe(receiver.start(self.synchronizer), self._async_loop)
        future.result()
        
        logger.info("Main telemetry cycle active. Listening for 120Hz UDP stream from Quest Pro...")
        
        while self.is_running and not self._shutdown_event.is_set():
            if not self.gdpr_consent:
                logger.error("Consent revoked during active sampling.")
                break
            time.sleep(0.5)
            
        receiver.stop()

    def _teardown(self) -> None:
        logger.info("Executing deterministic teardown sequence...")
        self.is_running = False
        self._shutdown_event.set()

        self.synchronizer.stop()

        if self._async_loop and self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)

        if self._async_thread and self._async_thread.is_alive():
            self._async_thread.join(timeout=5.0)

        self.hardware.stop()
        self.writer.stop()  # Parquet file is fully flushed and closed after this line

        if getattr(self, "configured_backend", "auto") != "quest_udp" and self.backend:
            self.backend.shutdown()

        # Upload only after the writer has confirmed the file is sealed —
        # uploading a still-open/partially-flushed Parquet file would ship
        # corrupt or truncated data to the central server.
        self._upload_completed_session()

        logger.info(f"Telemetry engine shutdown complete.")

    def _upload_completed_session(self) -> None:
        try:
            static_meta = self.subject_metadata.get("M-IV_Static_Metadata", {})
            session_id = static_meta.get("session_id", self.session_id)

            summary_metadata = {
                "session_id": session_id,
                "subject_id": static_meta.get("subject_id"),
                "total_frames": self.frames_recorded,
                "duration_sec": None,  # left for the central server to derive from the Parquet file itself if needed
            }

            result = self.uploader.upload(self.parquet_path, session_id, summary_metadata)
            if result.get("ok"):
                logger.info(f"Session {session_id} synced to central server.")
            else:
                logger.warning(f"Session {session_id} could not be synced now "
                                f"(reason: {result.get('reason')}) — queued for retry.")
        except Exception as e:
            # Upload failure must never mask/replace the "recording completed successfully"
            # outcome — the researcher's data is already safe on local disk regardless.
            logger.error(f"Unexpected error during post-session upload: {e}")