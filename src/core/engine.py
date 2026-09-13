# src/core/engine.py
import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from src.application.recording_context import (
    RecordingDependencies,
    build_recording_dependencies,
)
from src.backends.registry import create_backend
from src.backends.udp_receiver import NativeQuestReceiver
from src.config import get_settings
from src.core.exceptions import (
    BackendUnavailableError,
    GDPRConsentError,
    StorageWriteError,
    SynchronizationError,
    VRTelemetryError,
)
from src.core.interfaces import IVRBackend
from src.core.live_state import LiveExperimentState
from src.core.synchronizer import BiometricSynchronizer
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
        dependencies: RecordingDependencies | None = None,
        backend: str = "auto",
        network_port: int = 5005,
        event_router: Any | None = None,
    ):
        """Prepare a recording. Nothing is started and no thread is spawned.

        Args:
            output_dir: Where the Parquet file goes. Defaults to configuration.
            gdpr_consent: Must be true. A last-line guard, not the consent
                check itself: both callers (the recording route and the CLI)
                pass True only after the participant's recorded consent has
                been validated against the consent register (GDPR-09).
            subject_metadata: Pre-built metadata block, or None to construct the
                default one.
            hardware_metadata: Capability map, folded into the default block.
            central_server_url: Hub address for this session's uploads.
            backend: Which acquisition backend to use, resolved through
                :mod:`src.backends.registry`. Both callers used to assign
                ``engine.configured_backend`` after construction, so the
                attribute did not exist on the class and every read was a
                ``getattr(self, ..., "auto")`` that would have silently used the
                default if the assignment were ever forgotten -- and mypy could
                not see the attribute at all.
            network_port: UDP port for ``"quest_udp"``. Same story.
            dependencies: The sink, metrics source, metadata sink and uploader
                (VRT-14). ``None`` builds the production set, which is what the
                API route and the CLI want. A test passes fakes and gets a full
                recording lifecycle with no disk, no network and no hardware --
                see tests/integration/test_recording_lifecycle.py.

                Note the asymmetry with the API's container, which has no such
                default: these are session-scoped (the writer's path carries the
                session id), so there is no earlier place for a caller to build
                them, and requiring it would put four constructors into both
                call sites.
            event_router: The VR Telemetry Hub's plugin Event Router
                (src.interfaces.api.event_router.EventRouter), or None. Typed
                Any so src/core never imports src/interfaces/api (dependencies
                point inward). An observer only -- wrapped around self.writer
                via TeeFrameSink, which is what keeps a plugin subsystem from
                ever affecting write_failed or otherwise influencing the
                recording. None (the default) reproduces today's behaviour
                exactly.

        Raises:
            GDPRConsentError: if consent was not asserted.
        """
        settings = get_settings()
        max_sampling_hz = settings.acquisition.default_max_sampling_hz

        if not gdpr_consent:
            raise GDPRConsentError(
                "CRITICAL: Biometric tracking initialization aborted. Explicit user GDPR consent missing."
            )

        self.is_running = False
        #: Frames the synchroniser accepted -- what the session actually has.
        self.frames_recorded = 0
        #: Times the backend was asked for a frame. Kept apart from the above
        #: because they are wildly different numbers on a non-blocking backend,
        #: and conflating them is what made every frame count wrong (VRT-24).
        self.frames_polled = 0
        self.gdpr_consent = gdpr_consent
        self.configured_backend = backend
        self.network_port = network_port

        #: Why this session ended, when it ended badly (VRT-13). ``None`` means
        #: it ran to completion. Previously a session that never bound a headset,
        #: never opened its Parquet file or died in the acquisition loop all
        #: looked identical from outside: `start()` returned, `is_running` went
        #: False, and the reason existed only in a log line. The API and the CLI
        #: read this to say what actually happened.
        self.failure_reason: str | None = None

        # Declared here rather than only in start(). The attribute was created
        # partway through start()'s backend-selection branch, so between
        # construction and that branch the object had no `backend` attribute at
        # all -- any access raised AttributeError instead of reading None. That
        # is what made tests/integration/test_pipeline.py fail on every machine,
        # headset or not. Selection now goes through src.backends.registry.
        self.backend: IVRBackend | None = None
        self.live_state = LiveExperimentState()
        self._last_frame_ts_ns: int | None = None

        self.output_dir = Path(output_dir) if output_dir else settings.paths.sessions_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._session_wall_start_ts: float | None = None
        self._session_wall_end_ts: float | None = None
        #: Where this session's captured log was written, set at teardown.
        self.session_log_path: Path | None = None

        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.parquet_path = self.output_dir / f"vr_telemetry_{self.session_id}.parquet"

        # 1. The collaborators. Built here only when the caller did not supply
        # them: this constructor used to open a SQLite database, read the
        # licence cache and construct an HTTP client unconditionally, which is
        # why there was no way to exercise a recording without a disk and a
        # network. An unconfigured hub is a legitimate state -- uploads queue
        # locally rather than being attempted against a placeholder address.
        self.dependencies = dependencies or build_recording_dependencies(
            self.parquet_path, central_server_url=central_server_url
        )
        # Named attributes as well as the dataclass, because six call sites and
        # three tests already say `engine.writer`. They are the same objects;
        # `self.dependencies` is what a new caller should read.
        self.writer = self.dependencies.writer

        # VR Telemetry Hub plugin architecture: an *observer* only -- see
        # src/storage/tee_sink.py's docstring for why this can never affect
        # write_failed or otherwise influence the recording. Uses
        # self.session_id, already assigned above this point.
        if event_router is not None:
            from src.storage.tee_sink import TeeFrameSink

            self.writer = TeeFrameSink(
                self.writer, event_router.frame_sink_for_session(self.session_id)
            )

        self.hardware = self.dependencies.hardware
        self.db_manager = self.dependencies.metadata_sink
        self.uploader = self.dependencies.uploader

        # 2. Initialize synchronizer AFTER its dependencies (writer, hardware, live_state) exist
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
            # No guard: collect_system_profile() is documented never to raise and
            # returns whatever it managed to collect. The try/except that used to
            # be here was the only caller that guarded it -- start() below has
            # always called it bare -- so the two disagreed about whose job the
            # failure was, which is the condition under which a real fault ends
            # up handled by neither.
            self.subject_metadata["S-IX_System_Profile"] = collect_system_profile()

    def _start_async_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Run the consumer loop on its own thread.

        Takes the loop rather than reading ``self._async_loop``. That attribute
        is legitimately ``None`` between construction and ``start()``, so every
        use of it here was an access on an Optional -- eleven of the type
        checker's complaints about this file, and each one a real "if this ran
        at the wrong moment it would be an AttributeError". Passing it makes the
        ordering a fact of the signature instead of an assumption.

        Args:
            loop: The event loop this thread owns and closes.
        """
        asyncio.set_event_loop(loop)

        self.synchronizer.start(loop)

        try:
            loop.run_forever()
        except Exception as e:  # noqa: BLE001 - thread top level: nothing above it can catch
            # This thread owns the only consumer of the ring buffer. If it dies,
            # the acquisition loop keeps polling and pushing into a buffer that
            # nothing drains, and the session ends reporting frames that were
            # never written. So the failure is recorded and acquisition is told
            # to stop, rather than logged and left to run on.
            self.failure_reason = f"consumer thread failed: {e}"
            logger.critical(f"AsyncIO Loop Exception -- halting acquisition: {e}", exc_info=True)
            self._shutdown_event.set()
        finally:
            pending = asyncio.all_tasks(loop=loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

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

        self.hardware.start()
        try:
            self.writer.start()
        except StorageWriteError as exc:
            # The sink could not be opened. Everything after this point would
            # record frames into nothing, so the session does not start at all
            # and says why -- rather than running to completion and leaving an
            # empty file for someone to find later.
            self.failure_reason = f"storage unavailable: {exc}"
            logger.critical(f"Recording aborted before the first frame: {exc}")
            self.hardware.stop()
            self.session_log_path = detach_session_log_capture(self._session_log_handler)
            return

        # Called once. It used to be called twice in a row with the first
        # return value discarded, which is the same swallowed-failure shape this
        # ticket is about: whichever of the two failed, the log recorded at most
        # one of them, and a duplicate INSERT of the same session's metadata was
        # the successful case.
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
        except Exception as e:  # noqa: BLE001 - boot step: an unreachable hub must not block recording
            # Deliberately the tolerant side of the rule. This sweep is about
            # *previous* sessions; a researcher on a laptop with no route to the
            # hub must still be able to press record. The queue is durable and
            # BackgroundSyncScheduler retries it every 20s regardless.
            logger.warning(f"Pending upload retry sweep failed (will retry next start): {e}")

        self._shutdown_event.clear()
        loop = self._async_loop = asyncio.new_event_loop()

        self._async_thread = threading.Thread(
            target=self._start_async_loop,
            args=(loop,),
            daemon=True,
            name="TelemetryConsumerThread",
        )
        self._async_thread.start()

        self._session_wall_start_ts = time.time()

        self.is_running = True
        backend_mode = self.configured_backend

        try:
            if backend_mode == "quest_udp":
                # Not a backend: the Quest streams frames into the synchroniser
                # over a socket, so there is nothing to poll. See the note in
                # src/backends/registry.py about folding both shapes into one
                # FrameSource port.
                self._run_quest_udp_mode()
            else:
                # One line where there were five, and the difference is not the
                # line count: an unrecognised name used to fall through the
                # `else` and start a SteamVR session, so `--backend openxrr`
                # recorded a study on the wrong device without a word. The
                # registry raises instead, and the raise lands in the
                # VRTelemetryError clause below as a stated failure_reason.
                self.backend = create_backend(backend_mode)
                self._run_pcvr_mode(self.backend)

        except KeyboardInterrupt:
            logger.warning("Telemetry capture sequence interrupted manually.")
        except VRTelemetryError as e:
            # A failure this application anticipated -- no headset, no storage,
            # consent revoked. Reportable as a reason, not as a crash.
            self.failure_reason = str(e)
            logger.error(f"Recording stopped: {e}")
        except Exception as e:  # noqa: BLE001 - session boundary: teardown must run whatever happened
            # Anything else is a defect. It still must not escape past the
            # `finally` -- the writer has to be sealed and the log detached or
            # the session's data is unrecoverable -- but it is logged with its
            # traceback and named as unexpected, rather than reduced to one line
            # that reads like the expected case.
            self.failure_reason = f"unexpected error: {e}"
            logger.critical(f"Unexpected exception in main loop: {e}", exc_info=True)
        finally:
            self._teardown()

    def stop(self) -> None:
        """Ask the acquisition loop to finish.

        Returns immediately. The loop notices on its next iteration, falls out
        of :meth:`start`, and ``start``'s ``finally`` runs :meth:`_teardown` --
        which seals the Parquet file, joins the consumer thread and uploads. So
        "stopped" means "asked to stop"; the caller that needs the session
        finished waits on the thread it started.

        Both flags are set. ``is_running`` ends the PCVR poll loop and
        ``_shutdown_event`` ends the UDP one, and a stop that set only the first
        would leave a Quest session running.

        **This method did not exist until VRT-14**, which makes two comments
        elsewhere in the tree wrong in an instructive way.
        ``RecordingSessionManager.stop`` reads::

            if hasattr(engine, "stop"):
                engine.stop()
            else:
                engine.is_running = False

        and VRT-12's note beside it says "TelemetryEngine has always had
        ``stop()``, so that fallback never ran". The opposite was true: the
        engine never had one, so the fallback was the only path that had ever
        run and the ``hasattr`` branch was dead. It worked, because setting the
        flag is what stopping amounts to -- but "the manager reaches in and
        mutates the engine's attribute" is not a contract, and the comment
        asserting otherwise had been read and believed at least twice.
        """
        self.is_running = False
        self._shutdown_event.set()

    def _run_pcvr_mode(self, backend: IVRBackend) -> None:
        """Poll ``backend`` until the session ends.

        Args:
            backend: The bound acquisition backend. Passed rather than read from
                ``self.backend``, which is Optional until ``start()`` selects
                one -- so every use inside this method was an access on a value
                the type checker knew could be None, and a caller could invoke
                it before selection and get an AttributeError.
        """
        logger.info(f"Initializing Native Context via {backend.__class__.__name__}...")
        if not backend.initialize():
            # Raised rather than returned. `return` here left start() to run its
            # `finally` and exit normally, so a workstation with no headset
            # produced a completed session with zero frames and no stated cause;
            # the only trace was one ERROR line in a log nobody reads unless
            # something already looks wrong.
            raise BackendUnavailableError(
                f"{backend.__class__.__name__} could not bind to a VR runtime. "
                f"Check that the headset is connected and its runtime is running."
            )

        detected_hz = getattr(backend, "get_refresh_rate_hz", lambda: None)()
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

        # Pacing (VRT-24). "Listening for HMD pacing" was aspirational: it is
        # true of OpenXR, whose poll_frame blocks in `xr.wait_frame`, and false
        # of SteamVR's overlay path, which reads *predicted* poses and returns
        # immediately. Measured against a non-blocking backend, this loop ran at
        # ~131,000 Hz and the synchroniser discarded 99.92% of what it produced
        # -- a core pinned at 100% for the length of a session, competing with
        # the compositor on the same machine, to throw away 392,633 of 392,956
        # frames.
        #
        # Sleeping until the next sample is due costs a blocking backend
        # nothing: if poll_frame already took longer than the interval, the
        # remaining time is negative and there is no sleep. Deadlines are
        # advanced absolutely rather than by "sleep(interval)" so that a slow
        # frame does not push every later one late.
        next_due_ns = time.perf_counter_ns()

        while self.is_running and not self._shutdown_event.is_set():
            if not self.gdpr_consent:
                logger.error("Consent revoked during active sampling.")
                break

            # `self.writer.write_failed`, not `getattr(..., False)`. The
            # defensive form defaulted a *missing* attribute to "everything is
            # fine", so a sink that could not report failure was read as one
            # that had not failed. FrameSink makes the attribute part of the
            # contract instead (VRT-14).
            if self.writer.write_failed:
                logger.critical(
                    "Parquet writer has failed — stopping acquisition rather than continuing to "
                    "collect frames that cannot be persisted."
                )
                break

            frame_data = backend.poll_frame(self.frames_polled)
            self.frames_polled += 1

            # Only where the timestamp is the runtime's display time. On the
            # SteamVR path it is `time.perf_counter_ns()` read at the moment we
            # asked, so this arithmetic yielded our own polling rate -- about
            # 131,000 "fps" -- written into the app_fps column of every frame in
            # the dataset. See IVRBackend.timestamp_is_display_time.
            if backend.timestamp_is_display_time:
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
            if has_valid_source and self.synchronizer.push_frame(frame_data):
                # Accepted, not merely offered. This counted every *poll* until
                # VRT-24, so a three-second session reported 392,956 frames and
                # persisted 322 of them -- and that number is what teardown logs
                # and what `total_frames` sends to the hub.
                self.frames_recorded += 1

            interval_ns = self.synchronizer.sample_interval_ns
            if interval_ns:
                next_due_ns += interval_ns
                remaining_ns = next_due_ns - time.perf_counter_ns()
                if remaining_ns > 0:
                    time.sleep(remaining_ns / 1e9)
                else:
                    # Behind schedule: reset the deadline instead of
                    # accumulating debt and then free-running to catch up.
                    next_due_ns = time.perf_counter_ns()

    def _run_quest_udp_mode(self) -> None:
        """Headless network loop catching native Quest Pro biometric payloads."""
        if not get_settings().acquisition.enable_quest_udp:
            # GDPR-12. The receiver listens on every interface and accepts
            # unauthenticated, unencrypted datagrams from anyone on the LAN.
            # No sender for it exists in this repository and recordings go
            # through OpenXR, so it is off unless deliberately switched on.
            raise BackendUnavailableError(
                "The quest_udp receiver is disabled (acquisition.enable_quest_udp = false): it "
                "accepts unencrypted, unauthenticated telemetry from the network. Record through "
                "OpenXR instead."
            )
        port = self.network_port
        self.synchronizer.set_max_hz(120.0)
        logger.info(f"Bypassing PCVR Runtimes. Booting Native UDP Receiver on port {port}...")

        receiver = NativeQuestReceiver(port=port)

        loop = self._async_loop
        if loop is None:  # pragma: no cover - start() creates it before branching here
            raise SynchronizationError(
                "The consumer loop was not started before UDP ingestion began."
            )

        future = asyncio.run_coroutine_threadsafe(receiver.start(self.synchronizer), loop)
        future.result()

        logger.info("Main telemetry cycle active. Listening for 120Hz UDP stream from Quest Pro...")

        while self.is_running and not self._shutdown_event.is_set():
            if not self.gdpr_consent:
                logger.error("Consent revoked during active sampling.")
                break
            if self.writer.write_failed:
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

        # A session that captured nothing is a failed session, and until now it
        # did not look like one: the Parquet file was sealed, the session was
        # uploaded and synced, and the UI showed a normal completed recording
        # whose emptiness the researcher only discovered on opening it. Every
        # openxr_headless run on 12 Sep did exactly this. The engine already has
        # a channel for "this session ended with a reason" -- use it, so the
        # answer arrives when the participant is still in the room.
        if self.frames_recorded == 0 and self.failure_reason is None:
            self.failure_reason = (
                f"No telemetry was captured: the backend was polled {self.frames_polled} times "
                "and not one frame reached storage. The session file is empty. See the tracking "
                "fault summary for which source was failing."
            )
            logger.error(self.failure_reason)

        if self._async_loop and self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)

        if self._async_thread and self._async_thread.is_alive():
            self._async_thread.join(timeout=5.0)

        # Hand the VR runtime back its handles (instance, session, spaces, eye
        # driver). Nothing called this before: IVRBackend.shutdown() exists and
        # all four backends implement it, but its only caller was each
        # backend's own initialize() failure path -- so a *successful*
        # recording leaked its OpenXR instance and session for the life of the
        # backend process, and the next recording's xrCreateInstance then died
        # inside the runtime with an access violation rather than an exception.
        # Safe here: start()'s finally runs teardown on the engine thread, so
        # the poll loop has already exited and the synchronizer above has
        # drained. Broad catch because everything below still has to seal and
        # upload the session -- a driver that misbehaves on the way out must
        # not cost the researcher the recording it just made.
        if self.backend:
            try:
                self.backend.shutdown()
            except Exception:  # noqa: BLE001 - teardown: the session below still has to be sealed and uploaded
                logger.exception("Backend shutdown failed; continuing teardown.")
            finally:
                self.backend = None

        self.hardware.stop()
        self.writer.stop()

        if self.writer.write_failed:
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
            log_path = self.session_log_path
            if log_path is not None and log_path.exists():
                log_result = self.uploader.upload_log(log_path, session_id)
                if not log_result.get("ok"):
                    logger.warning(
                        f"Session log upload failed for {session_id}: "
                        f"{log_result.get('reason')} — queued for retry."
                    )

        except Exception as e:  # noqa: BLE001 - teardown: the data is already on disk and safe
            # The last thing that runs, after the Parquet file is sealed. An
            # upload that fails here costs a sync, not a session, and the
            # pending queue picks it up. What it must not do is raise out of
            # _teardown() and skip the shutdown log line, which is how a session
            # that recorded perfectly ends up looking like one that crashed.
            logger.error(f"Unexpected error during post-session upload: {e}", exc_info=True)
