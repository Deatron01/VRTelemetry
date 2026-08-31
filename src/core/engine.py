# src/core/engine.py
import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from src.backends.backend_ocolus import OculusBackend
from src.backends.backend_openxr import OpenXRBackend
from src.backends.backend_steamvr import SteamVROverlayBackend
from src.backends.udp_receiver import NativeQuestReceiver
from src.config import get_settings
from src.core.exceptions import GDPRConsentError
from src.core.interfaces import IVRBackend
from src.core.live_state import LiveExperimentState
from src.core.synchronizer import BiometricSynchronizer
from src.license_service.local_cache import LocalLicenseCache
from src.storage.database_manager import DatabaseManager
from src.storage.parquet_writer import AsyncParquetWriter
from src.storage.session_uploader import SessionUploader
from src.utils.hardware_monitor import HardwareMonitor
from src.utils.logger import attach_session_log_capture, detach_session_log_capture, logger
from src.utils.system_profiler import collect_system_profile


class TelemetryEngine:
    """
    Production telemetry orchestrator. Guarantees deterministic synchronization between
    the OpenXR hardware pacing loop (or UDP sockets) and the asynchronous I/O storage subsystems.
    """

    def __init__(
        self,
        output_dir: str | Path | None = None,
        gdpr_consent: bool = False,
        subject_metadata: dict[str, Any] | None = None,
        hardware_metadata: dict[str, Any] | None = None,
        central_server_url: str | None = None,
    ):
        settings = get_settings()
        max_sampling_hz = settings.acquisition.default_max_sampling_hz

        if not gdpr_consent:
            raise GDPRConsentError(
                "CRITICAL: Biometric tracking initialization aborted. Explicit user GDPR consent missing."
            )

        self.is_running = False
        self.frames_recorded = 0
        self.gdpr_consent = gdpr_consent

        # Declared here rather than only in start(). The attribute was created
        # partway through start()'s backend-selection branch, so between
        # construction and that branch the object had no `backend` attribute at
        # all -- any access raised AttributeError instead of reading None. That
        # is what made tests/integration/test_pipeline.py fail on every machine,
        # headset or not. Backend selection moves to a registry in VRT-14.
        self.backend: IVRBackend | None = None
        self.live_state = LiveExperimentState()
        self._last_frame_ts_ns: int | None = None

        self.output_dir = Path(output_dir) if output_dir else settings.paths.sessions_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._session_wall_start_ts: float | None = None
        self._session_wall_end_ts: float | None = None

        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.parquet_path = self.output_dir / f"vr_telemetry_{self.session_id}.parquet"

        # 1. Initialize core storage and hardware monitors FIRST
        self.db_manager = DatabaseManager()
        self.hardware = HardwareMonitor()
        self.writer = AsyncParquetWriter(output_path=self.parquet_path, target_hz=120)

        # 2. Initialize license cache and uploader
        self.local_license_cache = LocalLicenseCache()
        # None is a legitimate state: an unconfigured hub means uploads queue
        # locally rather than being attempted against a placeholder address.
        self.uploader = SessionUploader(
            central_server_url or settings.central.url or "", self.local_license_cache
        )

        # 3. Initialize synchronizer AFTER its dependencies (writer, hardware, live_state) exist
        self.synchronizer = BiometricSynchronizer(
            writer=self.writer,
            hardware_monitor=self.hardware,
            max_hz=max_sampling_hz,
            live_state=self.live_state,
        )

        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()

        self.subject_metadata = subject_metadata or {
            "M-IV_Static_Metadata": {"session_id": self.session_id, "subject_id": "SUB_UNKN_01"},
            "H-VII_Hardware_Capabilities": hardware_metadata or {},
        }

        if "S-IX_System_Profile" not in self.subject_metadata:
            try:
                self.subject_metadata["S-IX_System_Profile"] = collect_system_profile()
            except Exception as e:
                logger.warning(
                    f"System profile collection failed, continuing with empty profile: {e}"
                )
                self.subject_metadata["S-IX_System_Profile"] = {}

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

        self._session_log_handler = attach_session_log_capture(self.session_id)

        system_profile = collect_system_profile()
        self.subject_metadata.setdefault("S-IX_System_Profile", {})
        self.subject_metadata["S-IX_System_Profile"].update(system_profile)

        self.db_manager.persist_experiment(self.subject_metadata)
        self.hardware.start()
        self.writer.start()
        persisted = self.db_manager.persist_experiment(self.subject_metadata)
        if not persisted:
            logger.error(
                "Session metadata failed to persist — recording will continue, but this session's "
                "subject/hardware/system profile will be MISSING from the database."
            )
        # Sweep anything left over from a prior offline session before starting new work.
        # Non-blocking in spirit — a slow/unreachable server here just logs and moves on,
        # it must never delay the actual telemetry loop from starting.
        try:
            retry_result = self.uploader.retry_pending()
            if retry_result["attempted"]:
                logger.info(
                    f"Retried {retry_result['attempted']} pending upload(s) from previous sessions, "
                    f"{retry_result['succeeded']} succeeded."
                )
        except Exception as e:
            logger.warning(f"Pending upload retry sweep failed (will retry next start): {e}")

        self._shutdown_event.clear()
        self._async_loop = asyncio.new_event_loop()

        self._async_thread = threading.Thread(
            target=self._start_async_loop, daemon=True, name="TelemetryConsumerThread"
        )
        self._async_thread.start()

        self._session_wall_start_ts = time.time()

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
                else:  # "auto" vagy "steamvr" esetén
                    self.backend = SteamVROverlayBackend()

                self._run_pcvr_mode()

        except KeyboardInterrupt:
            logger.warning("Telemetry capture sequence interrupted manually.")
        except Exception as e:
            logger.error(f"Critical runtime exception in main loop: {e}")
        finally:
            self._teardown()

    def _run_pcvr_mode(self) -> None:
        logger.info(f"Initializing Native Context via {self.backend.__class__.__name__}...")
        if not self.backend.initialize():
            logger.error("Failed to bind PCVR session. Terminating execution.")
            return

        detected_hz = getattr(self.backend, "get_refresh_rate_hz", lambda: None)()
        if detected_hz and detected_hz > 0:
            headroom = get_settings().acquisition.sampling_headroom
            cap = max(30.0, min(500.0, detected_hz * headroom))
            self.synchronizer.set_max_hz(cap)
            self.subject_metadata["M-IV_Static_Metadata"]["hmd_refresh_rate"] = detected_hz
            logger.info(
                f"Detected live HMD refresh rate: {detected_hz:.1f} Hz — sampling cap set to {cap:.1f} Hz."
            )
        else:
            logger.warning(
                f"Could not detect live refresh rate; using default sampling cap of "
                f"{self.synchronizer.max_hz:.1f} Hz."
            )

        logger.info("Main telemetry cycle active. Listening for HMD pacing.")

        while self.is_running and not self._shutdown_event.is_set():
            if not self.gdpr_consent:
                logger.error("Consent revoked during active sampling.")
                break

            if getattr(self.writer, "write_failed", False):
                logger.critical(
                    "Parquet writer has failed — stopping acquisition rather than continuing to "
                    "collect frames that cannot be persisted."
                )
                break

            frame_data = self.backend.poll_frame(self.frames_recorded)

            if (
                self._last_frame_ts_ns is not None
                and frame_data.timestamp_ns > self._last_frame_ts_ns
            ):
                dt = (frame_data.timestamp_ns - self._last_frame_ts_ns) / 1e9
                if dt > 0:
                    frame_data.app_fps = 1.0 / dt
            self._last_frame_ts_ns = frame_data.timestamp_ns

            # A frame with zero valid tracking sources is the stub returned when the
            # session isn't ready — recording it corrupts the dataset with fake all-zero rows.
            has_valid_source = (
                frame_data.hmd_tracking_valid > 0
                or frame_data.left_tracking_valid > 0
                or frame_data.right_tracking_valid > 0
                or frame_data.eye_tracking_valid > 0
            )
            if has_valid_source:
                self.synchronizer.push_frame(frame_data)
                self.frames_recorded += 1

    def _run_quest_udp_mode(self) -> None:
        """Headless network loop catching native Quest Pro biometric payloads."""
        port = getattr(self, "network_port", 5005)
        self.synchronizer.set_max_hz(120.0)
        logger.info(f"Bypassing PCVR Runtimes. Booting Native UDP Receiver on port {port}...")

        receiver = NativeQuestReceiver(port=port)

        future = asyncio.run_coroutine_threadsafe(
            receiver.start(self.synchronizer), self._async_loop
        )
        future.result()

        logger.info("Main telemetry cycle active. Listening for 120Hz UDP stream from Quest Pro...")

        while self.is_running and not self._shutdown_event.is_set():
            if not self.gdpr_consent:
                logger.error("Consent revoked during active sampling.")
                break
            if getattr(self.writer, "write_failed", False):
                logger.critical(
                    "Parquet writer has failed — stopping UDP ingestion rather than continuing to "
                    "collect frames that cannot be persisted."
                )
                break
            time.sleep(0.5)

        receiver.stop()

    def _teardown(self) -> None:
        logger.info("Executing deterministic teardown sequence...")
        self.is_running = False
        self._shutdown_event.set()

        self.synchronizer.stop()
        logger.info(
            f"Sampling summary: {self.frames_recorded} frames recorded, "
            f"{self.synchronizer.dropped_backpressure} dropped (buffer full), "
            f"{self.synchronizer.dropped_oversampling} dropped (oversampling cap)."
        )

        if self._async_loop and self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)

        if self._async_thread and self._async_thread.is_alive():
            self._async_thread.join(timeout=5.0)

        self.hardware.stop()
        self.writer.stop()

        if getattr(self.writer, "write_failed", False):
            logger.critical(
                f"Session {self.session_id}: the Parquet writer failed partway through recording. "
                f"The reported frame count ({self.frames_recorded}) does NOT reflect what was actually "
                f"persisted to disk — treat this session's data as incomplete/unreliable."
            )

        self.session_log_path = detach_session_log_capture(self._session_log_handler)

        self._upload_completed_session()

        logger.info("Telemetry engine shutdown complete.")

    def _upload_completed_session(self) -> None:
        try:
            static_meta = self.subject_metadata.get("M-IV_Static_Metadata", {})
            session_id = static_meta.get("session_id", self.session_id)

            duration_sec = None
            if self._session_wall_start_ts is not None and self._session_wall_end_ts is not None:
                duration_sec = round(self._session_wall_end_ts - self._session_wall_start_ts, 3)

            summary_metadata = {
                "session_id": session_id,
                "subject_id": static_meta.get("subject_id"),
                # Links this upload back to the patient record centrally, so the
                # admin dashboard's patient view can show real session counts
                # instead of only what's visible in the researcher's local DB.
                "patient_id": static_meta.get("patient_id"),
                "total_frames": self.frames_recorded,
                "duration_sec": duration_sec,
            }

            result = self.uploader.upload(self.parquet_path, session_id, summary_metadata)
            if result.get("ok"):
                logger.info(f"Session {session_id} synced to central server.")
            else:
                logger.warning(
                    f"Session {session_id} could not be synced now "
                    f"(reason: {result.get('reason')}) — queued for automatic retry."
                )

            # Log upload is best-effort and independent of the Parquet upload outcome —
            # even a session whose data upload failed should still get its diagnostic
            # log shipped if possible, since that log might explain *why* it failed.
            # queue_on_failure=True (the default) means a failure here is queued
            # in pending_session_logs and retried by the BackgroundSyncScheduler,
            # rather than being silently lost.
            if getattr(self, "session_log_path", None) and self.session_log_path.exists():
                log_result = self.uploader.upload_log(self.session_log_path, session_id)
                if not log_result.get("ok"):
                    logger.warning(
                        f"Session log upload failed for {session_id}: "
                        f"{log_result.get('reason')} — queued for retry."
                    )

        except Exception as e:
            logger.error(f"Unexpected error during post-session upload: {e}")
