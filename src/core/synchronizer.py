import asyncio
import logging
import threading
from collections import deque

from src.core.datatypes import TelemetryFrame
from src.core.derived_metrics import compute_binocular_focal_distance, compute_distance
from src.core.live_biometrics import LiveBiometricState
from src.core.live_state import LiveExperimentState

logger = logging.getLogger(__name__)


class BiometricSynchronizer:
    """
    Lock-free ring buffer decoupling the hardware ingestion thread from the AsyncIO
    disk-writing thread. Also enforces an optional sampling-rate ceiling so bursty or
    duplicate-heavy sources (UDP floods, polling-loop artifacts) aren't recorded as if
    every burst were a unique physical sample.
    """

    def __init__(
        self,
        writer,
        hardware_monitor,
        buffer_size: int = 5000,
        max_hz: float | None = None,
        live_state: LiveExperimentState | None = None,
        live_biometrics: LiveBiometricState | None = None,
    ):
        self.writer = writer
        self.hardware = hardware_monitor
        self.live_state = live_state
        #: Out-of-process biosensor plugins (VRT-32). Kept a separate
        #: parameter from ``live_state`` rather than folded into it: that
        #: class's fields are set by *this* application's own UI/routes,
        #: while this one is set by a third-party producer over the network
        #: -- different trust boundary, different staleness rule (a horizon,
        #: not a caller-supplied duration), worth keeping visibly separate.
        self.live_biometrics = live_biometrics

        self._buffer_size = buffer_size
        self._buffer: deque[tuple] = deque(maxlen=buffer_size)
        self._is_running = False
        self._async_task: asyncio.Task | None = None

        #: Set while no consumer is running, and by the consumer itself on the
        #: way out. :meth:`stop` waits on it, so "stopped" means "everything
        #: buffered actually reached the writer", not merely "asked to stop".
        #: Starts set so a synchronizer that was never started does not make
        #: stop() sit through its timeout.
        self._drained = threading.Event()
        self._drained.set()

        self.max_hz = max_hz
        self._min_interval_ns = int(1e9 / max_hz) if max_hz else None
        self._reject_below_ns = self._rejection_threshold_ns(self._min_interval_ns)
        self._last_accepted_ts_ns: int | None = None

        self.dropped_backpressure = 0  # buffer was full when we tried to append
        self.dropped_oversampling = 0  # frame arrived faster than the sampling cap allows
        self._last_backpressure_log = 0
        self._last_oversample_log = 0

        #: Batches the consumer loop failed to hand to the writer. Counted
        #: because the loop deliberately keeps running through a failure (see
        #: :meth:`_consume_loop`), and a survivable fault that nobody counts is
        #: how a session ends up short of frames with a clean-looking log.
        self.consume_faults = 0

    #: Fraction of the sampling interval a frame may arrive *early* and still be
    #: accepted. The acquisition loop paces itself to exactly
    #: :attr:`sample_interval_ns`, so the pacing period and the rejection
    #: threshold used to be the same number. OS sleep and runtime timing jitter
    #: then put roughly half of all genuine samples a fraction of a millisecond
    #: under the threshold: each one was discarded and left a double-length gap.
    #: Measured on 15 Sep 2026 (Vive Focus 3, OpenXR): inter-sample intervals
    #: split into two peaks at ~8.5 ms and ~16.5 ms, the effective rate fell from
    #: ~120 Hz to 60-66 Hz, and 21,973 of 55,388 polls were thrown away in one
    #: 7.7-minute session. Rejecting only what arrives in less than half an
    #: interval still stops the floods the cap exists for (duplicate display
    #: times, UDP bursts, a free-running loop) without eating jittered samples.
    JITTER_TOLERANCE = 0.5

    @classmethod
    def _rejection_threshold_ns(cls, min_interval_ns: int | None) -> int | None:
        if min_interval_ns is None:
            return None
        return int(min_interval_ns * (1.0 - cls.JITTER_TOLERANCE))

    def set_max_hz(self, max_hz: float) -> None:
        """Adjust the sampling ceiling at runtime — e.g. once the real device refresh rate is known."""
        self.max_hz = max_hz
        self._min_interval_ns = int(1e9 / max_hz) if max_hz else None
        self._reject_below_ns = self._rejection_threshold_ns(self._min_interval_ns)

    @property
    def sample_interval_ns(self) -> int | None:
        """Nanoseconds between accepted samples, or None when uncapped.

        Public because the acquisition loop paces itself to it. Before VRT-24
        that loop had no pacing at all: against a backend that returns without
        blocking -- which SteamVR's overlay path does, since it reads predicted
        poses rather than waiting on the compositor -- it polled at about
        130,000 Hz and this class discarded 99.9% of what it produced.
        """
        return self._min_interval_ns

    def push_frame(self, frame: TelemetryFrame) -> bool:
        """Called directly by the hardware/ingestion thread. Must be non-blocking.

        Returns:
            Whether the frame was accepted into the buffer. The caller counts
            accepted frames; it used to count *offered* ones, which is how a
            session that persisted 322 samples reported 392,956 of them to the
            hub (VRT-24).
        """
        if self._reject_below_ns is not None and self._last_accepted_ts_ns is not None:
            delta = frame.timestamp_ns - self._last_accepted_ts_ns
            # A duplicate (delta == 0: the runtime handed back the same display
            # time twice) or a burst well inside one sampling interval. Not a
            # frame that is merely a little early -- see JITTER_TOLERANCE.
            if 0 <= delta < self._reject_below_ns:
                self.dropped_oversampling += 1
                if self.dropped_oversampling - self._last_oversample_log >= 1000:
                    logger.warning(
                        f"Oversampling cap ({self.max_hz:.1f} Hz) rejected "
                        f"{self.dropped_oversampling} frame(s) so far — source is producing "
                        f"samples faster than the physical sensor rate."
                    )
                    self._last_oversample_log = self.dropped_oversampling
                return False

        self._last_accepted_ts_ns = frame.timestamp_ns

        # Fold in the latest low-frequency hardware metrics — HardwareMonitor already
        # computes these on its own thread, but nothing previously copied them into frames.
        frame.cpu_utilization = self.hardware.cpu_usage
        frame.voice_amplitude_db = self.hardware.voice_db
        frame.gpu_utilization = self.hardware.gpu_usage
        frame.gaze_focal_distance = compute_binocular_focal_distance(frame)

        if self.live_state is not None:
            snap = self.live_state.snapshot()
            frame.scene_id = snap["scene_id"]
            frame.event_marker = snap["event_marker"]
            frame.haptic_left_intensity = snap["haptic_left_intensity"]
            frame.haptic_right_intensity = snap["haptic_right_intensity"]

            tx, ty, tz = snap["target_obj_pos"]
            frame.target_obj_pos_x, frame.target_obj_pos_y, frame.target_obj_pos_z = tx, ty, tz
            if frame.left_tracking_valid > 0:
                frame.dist_to_target_left = compute_distance(
                    (frame.left_pos_x, frame.left_pos_y, frame.left_pos_z), (tx, ty, tz)
                )
            if frame.right_tracking_valid > 0:
                frame.dist_to_target_right = compute_distance(
                    (frame.right_pos_x, frame.right_pos_y, frame.right_pos_z), (tx, ty, tz)
                )

        if self.live_biometrics is not None:
            # VRT-32: the only channel a biosensor plugin can move into the
            # 120 Hz frame grid itself -- see LiveBiometricState's docstring
            # for why every other channel goes to the sidecar only, and
            # ``frame.timestamp_ns`` (not a fresh ``time.perf_counter_ns()``
            # call) for why staleness is judged against this frame's own
            # clock.
            frame.heart_rate_bpm = self.live_biometrics.read_heart_rate(frame.timestamp_ns)

        # `self._buffer_size`, not `self._buffer.maxlen`: deque types maxlen as
        # `int | None` because an unbounded deque is legal, and this one never is.
        if len(self._buffer) >= self._buffer_size:
            self.dropped_backpressure += 1
            if self.dropped_backpressure - self._last_backpressure_log >= 500:
                logger.warning(
                    f"Synchronizer buffer full — {self.dropped_backpressure} frame(s) dropped "
                    f"so far because the disk-writer thread is falling behind."
                )
                self._last_backpressure_log = self.dropped_backpressure

        self._buffer.append(frame.to_tuple())
        return True

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._is_running = True
        self._drained.clear()
        self._async_task = loop.create_task(self._consume_loop())
        cap_note = f" (sampling cap: {self.max_hz:.1f} Hz)" if self.max_hz else ""
        logger.info(f"Biometric synchronization buffer activated{cap_note}.")

    async def _consume_loop(self) -> None:
        try:
            await self._consume_until_drained()
        finally:
            # Reached only once every frame this loop popped has been handed to
            # the writer, which is what makes it a safe signal for stop() to
            # wait on -- including the case where the loop exits by raising.
            self._drained.set()

    async def _consume_until_drained(self) -> None:
        while self._is_running or len(self._buffer) > 0:
            try:
                batch: list[tuple] = []
                while len(self._buffer) > 0 and len(batch) < 120:
                    batch.append(self._buffer.popleft())

                if batch:
                    for frame_tuple in batch:
                        self.writer.push(frame_tuple)
                else:
                    await asyncio.sleep(0.001)

            # Broad on purpose (ruff accepts it here because the traceback is
            # logged rather than discarded).
            except Exception as e:
                # The one asyncio task draining the ring buffer into the writer.
                # If it raises, it is gone for the rest of the session and every
                # frame pushed afterwards is silently discarded by a producer
                # that has no idea -- the worst outcome available here, and worse
                # than continuing past one bad batch. So the catch stays broad
                # and the fault is counted and reported instead of swallowed.
                #
                # `batch` has already been popped off the buffer at this point,
                # so those frames are lost; that is what the count measures.
                self.consume_faults += 1
                logger.error(
                    f"Synchronizer batch {self.consume_faults} failed "
                    f"({len(batch)} frame(s) lost): {e}",
                    exc_info=True,
                )

    def stop(self, drain_timeout_sec: float = 5.0) -> None:
        pending = len(self._buffer)
        self._is_running = False

        # Wait for the consumer to finish, rather than only asking it to.
        # Clearing the flag lets the loop drain, but the engine's teardown stops
        # the event loop that loop runs on a few statements later -- so without
        # this, whatever was still buffered (plus any batch already popped but
        # not yet pushed) died with the loop, while frames_recorded had counted
        # every one of them on acceptance. That inflated count is what teardown
        # logs and what `total_frames` sends to the hub. It also made
        # test_the_reported_frame_count_is_what_the_sink_actually_received fail
        # about one run in three.
        drained = self._drained.wait(timeout=drain_timeout_sec)

        logger.info(
            f"Synchronizer shutting down. Flushing {pending} remaining frames to disk. "
            f"Dropped: {self.dropped_backpressure} (backpressure), "
            f"{self.dropped_oversampling} (oversampling cap)."
        )
        if not drained:
            logger.critical(
                f"The synchronizer's consumer did not drain within {drain_timeout_sec:.0f}s: "
                f"{len(self._buffer)} frame(s) were still buffered and have not reached the "
                f"writer. This session's frame count overstates what was persisted."
            )
        if self.consume_faults:
            logger.critical(
                f"{self.consume_faults} consumer batch(es) failed during this session -- "
                f"frames in those batches never reached the writer. This session's frame "
                f"count overstates what was persisted; treat the data as incomplete."
            )
