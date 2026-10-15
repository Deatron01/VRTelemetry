# src/core/live_biometrics.py
"""Thread-safe side-channel for out-of-process biosensor plugins (VRT-32).

Modelled directly on ``live_state.py``'s ``LiveExperimentState``: set from
FastAPI routes (the ``/api/biosensors/sample`` ingest route), read once per
frame by ``BiometricSynchronizer.push_frame()``, and defaulting to an honest
"nothing is happening" value (``0.0``) rather than a fabricated reading.

Distinct from ``LiveExperimentState`` because the two have different
staleness rules. A haptic pulse expires on a duration the caller supplied;
a heart-rate reading expires because the sensor may have lost contact or
the plugin process may have died, and nothing calls in to say so explicitly
-- the sensor plugin's own rule (see
``plugins/BIOSENSOR_INGEST.md``) is "stop sending,
don't repeat the last value." So staleness has to be a horizon this side
judges against the current frame's own clock, not a value the producer
pushes.

Only ``heart_rate_bpm`` is folded into ``TelemetryFrame`` -- the one
reserved channel name (see ``plugins/BIOSENSOR_INGEST.md``). Every other
channel a plugin sends (``rr_interval_ms``, ``spo2_pct``, ...) goes to the
sidecar (``src.storage.biosensor_sidecar``) only; this class does not need
to know their names.
"""

from __future__ import annotations

import threading


class LiveBiometricState:
    """The latest heart-rate sample, with a staleness horizon.

    ``> 0`` is a valid reading, ``0.0`` is absent -- the same convention
    ``TelemetryFrame.create_empty()`` and every reader of ``heart_rate_bpm``
    already use (Overview, Physiology, ResearchInsights, DataQuality,
    Metadata). Past the horizon, reads return ``0.0`` even though the last
    reported value might still be sitting in memory: forward-filling a stale
    reading is exactly what turns one lost BLE connection into thousands of
    fabricated samples in a session's summary statistics (host-changes doc
    §4).
    """

    def __init__(self, staleness_horizon_sec: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._staleness_horizon_ns = int(staleness_horizon_sec * 1e9)
        self._heart_rate_bpm = 0.0
        #: perf_counter_ns-equivalent arrival time of the last sample the
        #: ingest route accepted (see
        #: ``TelemetryEngine._biosensor_clock_offset_ns``). ``None`` means no
        #: sample has arrived yet this session.
        self._heart_rate_at_ns: int | None = None

    def record_heart_rate(self, value: float, arrival_perf_ns: int) -> None:
        """Called from the ingest route (any thread) for a ``heart_rate_bpm`` sample.

        Args:
            value: The reported reading. A plugin sending ``<= 0.0`` is
                reporting "no contact" per the ingest contract; that is not
                a valid reading and is not stored here -- storing it would
                just be a more roundabout way of forward-filling absence as
                if it were data, and the staleness horizon in
                :meth:`read_heart_rate` already produces ``0.0`` for "no
                recent reading" on its own.
            arrival_perf_ns: The sample's timestamp, already converted from
                the producer's ``t_wall_ns`` into this process's
                ``perf_counter_ns`` epoch (see
                ``TelemetryEngine._biosensor_clock_offset_ns``).
        """
        if value <= 0.0:
            return
        with self._lock:
            # Guards against an out-of-order delivery (a retried batch, a
            # slow request racing a newer one) silently rewinding "now" to an
            # older sample.
            if self._heart_rate_at_ns is not None and arrival_perf_ns < self._heart_rate_at_ns:
                return
            self._heart_rate_bpm = value
            self._heart_rate_at_ns = arrival_perf_ns

    def read_heart_rate(self, now_perf_ns: int) -> float:
        """Called once per frame from ``BiometricSynchronizer.push_frame()``.

        Args:
            now_perf_ns: The current frame's own ``perf_counter_ns``
                timestamp -- reusing the acquisition loop's own clock rather
                than calling ``time.perf_counter_ns()`` again here, so this
                reads as "stale relative to the frame it is being folded
                into," not "stale relative to whenever the consumer thread
                happened to get around to it."

        Returns:
            The last valid reading, or ``0.0`` if none has arrived yet or
            the last one is older than the staleness horizon.
        """
        with self._lock:
            if self._heart_rate_at_ns is None:
                return 0.0
            if now_perf_ns - self._heart_rate_at_ns > self._staleness_horizon_ns:
                return 0.0
            return self._heart_rate_bpm
