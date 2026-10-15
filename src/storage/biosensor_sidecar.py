# src/storage/biosensor_sidecar.py
"""Per-session long-format sidecar for biosensor samples (VRT-34).

A second, independent Parquet file next to the session's main
``vr_telemetry_<id>.parquet``: ``vr_biosensors_<id>.parquet``, one row per
sample rather than one row per frame, because a plugin's channels arrive at
whatever rate its device produces them (HR ~1 Hz, a raw ECG channel could be
130 Hz) -- forcing them onto the 120 Hz frame grid would mean inventing a
value for every frame nothing arrived on.

Deliberately modelled on ``AsyncParquetWriter``'s bounded-buffer,
sheds-under-backpressure shape rather than sharing code with it: this sink is
fed from FastAPI request threads (the ingest route), not from the single
acquisition/consumer thread, so it takes its own lock rather than relying on
one writer at a time. Unlike ``AsyncParquetWriter``, a failure here is never
a reason to stop the session: ``heart_rate_bpm``'s fold-in into the main
Parquet (``src.core.live_biometrics``) does not depend on this sidecar
keeping up, and this class's own failure state is read by nothing outside
``TelemetryEngine.ingest_biosensor_sample``, which already wraps every call
into this class in its own ``try/except`` for exactly that reason.

Authoritative-store decision (host-changes doc §6): the sidecar is
authoritative; the ``heart_rate_bpm`` column folded into the main per-frame
Parquet (``src.core.live_biometrics``) is a derived convenience copy. The
frame column is fed *from* ``LiveBiometricState``, which is fed from the
same ingest call as this sidecar, so the two agree by construction -- but
only the sidecar is queryable per-device/per-channel, and only the sidecar
(plus ``biosensor_streams``) is what ``src.application.erasure`` treats as
erasable on its own, via ``ErasureService.erase_biosensor_data`` (a future
``WithdrawalScope.BIOSENSOR_ONLY``) as well as a full
``ErasureService.erase``. The frame column is never redacted in place --
a full erasure removes it only because it deletes that whole Parquet file.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

#: Same fault classes ``AsyncParquetWriter`` treats as "the write failed,"
#: not "this file is broken" -- see that module for why the line is drawn
#: here and not at ``Exception``.
_WRITE_FAULTS = (pa.ArrowException, OSError, ValueError)

#: ``timestamp_ns`` is expected to already be in the main session Parquet's
#: ``perf_counter_ns`` epoch (see ``TelemetryEngine._biosensor_clock_offset_ns``
#: and the host-changes doc §5) so the two files can be joined on it without
#: a second conversion. ``quality`` is nullable: a producer that does not
#: know its own link quality sends ``null``, never a fabricated number.
_SCHEMA = pa.schema(
    [
        ("timestamp_ns", pa.int64()),
        ("device_id", pa.string()),
        ("channel", pa.string()),
        ("value", pa.float64()),
        ("quality", pa.float64()),
    ]
)


class BiosensorSidecarWriter:
    """Buffers ``(timestamp_ns, device_id, channel, value, quality)`` rows
    and flushes them to ``output_path`` in batches.
    """

    def __init__(
        self,
        output_path: Path,
        flush_interval_rows: int = 200,
        max_buffer_rows: int = 20_000,
    ) -> None:
        self.output_path = output_path
        self.flush_interval_rows = flush_interval_rows
        self.max_buffer_rows = max_buffer_rows

        self._lock = threading.Lock()
        self._buffer: list[tuple[int, str, str, float, float | None]] = []
        self._writer: pq.ParquetWriter | None = None
        self._file_obj: Any = None
        self.is_running = False
        #: Read by nothing outside this class and
        #: ``TelemetryEngine.ingest_biosensor_sample`` -- see this module's
        #: docstring for why a failure here never propagates further than
        #: "this sidecar stops accepting rows."
        self.write_failed = False
        self.dropped_backpressure = 0

    def start(self) -> None:
        try:
            self._file_obj = open(str(self.output_path), "wb")
            self._writer = pq.ParquetWriter(
                self._file_obj, _SCHEMA, compression="snappy", use_dictionary=True
            )
            self.is_running = True
            self.write_failed = False
            logger.info(f"Biosensor sidecar opened: {self.output_path.name}")
        except _WRITE_FAULTS as e:
            # Unlike AsyncParquetWriter.start(), this does not raise: a
            # sensor plugin that cannot be recorded to a sidecar is a gap in
            # one file, not a reason to fail the whole recording (the one
            # invariant the sensor plugin's own plan states -- "the plugin
            # must never fail, slow, or stop the telemetry recording it runs
            # alongside" -- applies just as much to the host side of the
            # same integration).
            self.write_failed = True
            logger.error(f"Biosensor sidecar could not open {self.output_path}: {e}")

    def push(
        self,
        timestamp_ns: int,
        device_id: str,
        channel: str,
        value: float,
        quality: float | None,
    ) -> None:
        """Non-blocking from the caller's point of view: appends and, at the
        flush threshold, flushes inline. Called from FastAPI request
        threads, never from the acquisition/consumer thread, so a flush
        taking a few milliseconds here costs an HTTP response, not a frame.
        """
        if not self.is_running or self.write_failed:
            return
        with self._lock:
            self._buffer.append((timestamp_ns, device_id, channel, float(value), quality))
            if len(self._buffer) > self.max_buffer_rows:
                overflow = len(self._buffer) - self.max_buffer_rows
                del self._buffer[:overflow]
                self.dropped_backpressure += overflow
                logger.warning(
                    f"Biosensor sidecar buffer exceeded {self.max_buffer_rows} rows -- "
                    f"dropped {overflow} oldest sample(s)."
                )
            if len(self._buffer) >= self.flush_interval_rows:
                self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._buffer or self._writer is None:
            return
        try:
            columns = list(zip(*self._buffer, strict=True))
            arrays = [pa.array(columns[i], type=field.type) for i, field in enumerate(_SCHEMA)]
            table = pa.Table.from_arrays(arrays, schema=_SCHEMA)
            self._writer.write_table(table)
            try:
                self._file_obj.flush()
                os.fsync(self._file_obj.fileno())
            except (OSError, ValueError) as fsync_err:
                logger.debug(f"fsync after biosensor sidecar flush failed (non-fatal): {fsync_err}")
            self._buffer.clear()
        except _WRITE_FAULTS as e:
            # One failure halts this sidecar only -- see the module
            # docstring. The main telemetry recording, and the
            # heart_rate_bpm frame-column fold-in (which reads from
            # LiveBiometricState, not from this class), are unaffected.
            self.write_failed = True
            self.is_running = False
            logger.error(
                f"Biosensor sidecar write failed; halting this sidecar only "
                f"(main recording is unaffected): {e}",
                exc_info=True,
            )

    def stop(self) -> None:
        with self._lock:
            if self._buffer:
                self._flush_locked()
            if self._writer is not None:
                try:
                    self._writer.close()
                    logger.info("Biosensor sidecar sealed.")
                except _WRITE_FAULTS as e:
                    self.write_failed = True
                    logger.error(f"Error sealing biosensor sidecar: {e}")
            if self._file_obj is not None:
                try:
                    self._file_obj.close()
                except OSError as e:
                    logger.debug(f"Error closing biosensor sidecar file handle: {e}")
        self.is_running = False
