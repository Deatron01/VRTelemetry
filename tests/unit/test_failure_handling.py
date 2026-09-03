# tests/unit/test_failure_handling.py
"""What VRT-13 changed about failing, proved rather than asserted.

The ticket's subject is not new behaviour but the *absence* of old behaviour:
sixty-nine handlers that used to reduce every failure to a log line, or to
nothing at all. That is awkward to test, because "the exception is no longer
swallowed" has no output to assert on -- so each test here pins the observable
consequence instead. A failure that now propagates, a counter that now moves, a
reason string that now exists.

The counterpart tests matter as much: a workstation with no hub, no headset and
no GPU must still start, and several tests below exist to fail if a later ticket
"fixes" the tolerant handlers along with the dishonest ones.
"""

from __future__ import annotations

import logging

import pyarrow as pa
import pytest

from src.backends.tracking_faults import REPEAT_LOG_INTERVAL, TrackingFaultLog
from src.core.engine import TelemetryEngine
from src.core.exceptions import (
    AcquisitionError,
    BackendUnavailableError,
    HardwareBindingError,
    StorageError,
    StorageWriteError,
    SynchronizationError,
    VRTelemetryError,
)
from src.core.synchronizer import BiometricSynchronizer
from src.storage.parquet_writer import AsyncParquetWriter
from src.storage.sync_scheduler import BackgroundSyncScheduler
from src.utils.system_profiler import collect_system_profile

# ─────────────────────────────────────────────────────────────────────────────
# The hierarchy
# ─────────────────────────────────────────────────────────────────────────────


def test_every_framework_error_is_catchable_as_one_thing():
    """`except VRTelemetryError` must mean "a failure we anticipated".

    The value of the base class is entirely in this property: a boundary that
    wants to distinguish an expected failure from a bug catches it, and gets
    that distinction only if nothing escapes the tree.
    """
    for error in (
        AcquisitionError,
        BackendUnavailableError,
        HardwareBindingError,
        StorageError,
        StorageWriteError,
        SynchronizationError,
    ):
        assert issubclass(error, VRTelemetryError)


def test_a_backend_that_cannot_bind_is_an_acquisition_error():
    """Callers catch categories, not leaves.

    `_run_pcvr_mode` raises the specific class; the engine's boundary catches
    `VRTelemetryError`; a future caller that wants only hardware problems
    catches `AcquisitionError`. All three have to work on the same object.
    """
    error = BackendUnavailableError("no runtime")
    assert isinstance(error, HardwareBindingError)
    assert isinstance(error, AcquisitionError)
    assert isinstance(error, VRTelemetryError)
    assert not isinstance(error, StorageError)


# ─────────────────────────────────────────────────────────────────────────────
# Storage: the write path does not swallow
# ─────────────────────────────────────────────────────────────────────────────


def test_a_writer_that_cannot_open_its_file_raises(tmp_path):
    """The sink failing to open ends the recording instead of starting it.

    Before: `start()` logged and re-raised a bare pyarrow/OS error, which the
    engine's blanket handler turned into one ERROR line in a session that then
    ran to completion with an empty file.
    """
    # A directory where the Parquet file should be: open() cannot open it.
    doomed = tmp_path / "not-a-file"
    doomed.mkdir()

    writer = AsyncParquetWriter(output_path=doomed, target_hz=90)
    with pytest.raises(StorageWriteError) as caught:
        writer.start()

    assert str(doomed) in str(caught.value)
    # The original OSError is preserved rather than replaced, so a traceback
    # still names the actual filesystem failure.
    assert caught.value.__cause__ is not None
    assert writer.is_running is False


def test_a_flush_failure_is_counted_and_eventually_halts_ingestion(tmp_path):
    """The one place in the write path that counts instead of raising.

    It runs on the asyncio consumer thread, where raising kills the only
    consumer and every later frame is dropped by a producer that never finds
    out. So it counts -- and `write_failed` is what the engine's loop reads to
    stop collecting frames it cannot persist.
    """
    writer = AsyncParquetWriter(
        output_path=tmp_path / "session.parquet", target_hz=90, max_consecutive_failures=2
    )
    writer.start()

    class _BrokenWriter:
        def write_table(self, _table):
            raise pa.ArrowInvalid("disk went away")

        def close(self):
            pass

    writer.writer = _BrokenWriter()

    writer.buffer = [("not", "a", "valid", "row")]
    writer._flush_buffer_to_disk()
    assert writer.consecutive_write_failures == 1
    assert writer.write_failed is False, "one failure is a hiccup, not a broken disk"

    writer.buffer = [("not", "a", "valid", "row")]
    writer._flush_buffer_to_disk()
    assert writer.write_failed is True
    assert writer.is_running is False


def test_a_writer_that_cannot_seal_its_file_marks_the_session_unreliable(tmp_path):
    """A truncated file is a data problem, not a shutdown detail.

    `stop()` used to log the close failure at ERROR and return, leaving
    `write_failed` False -- so the engine's teardown reported a clean session
    over a Parquet file with no valid footer.
    """
    writer = AsyncParquetWriter(output_path=tmp_path / "session.parquet", target_hz=90)
    writer.start()

    class _UncloseableWriter:
        def close(self):
            raise OSError("device disconnected")

    writer.writer = _UncloseableWriter()
    writer.stop()

    assert writer.write_failed is True


def test_a_bug_in_the_frame_tuple_is_not_reported_as_a_disk_failure(tmp_path):
    """The narrowing, stated as a test.

    `_WRITE_FAULTS` is pyarrow plus OSError plus ValueError. A TypeError from
    this file's own logic is outside it and travels, where previously it was
    counted as a "critical disk write failure" and, five of them later, told
    the researcher their disk had failed.
    """
    writer = AsyncParquetWriter(output_path=tmp_path / "session.parquet", target_hz=90)
    writer.start()

    class _TypeErroringWriter:
        def write_table(self, _table):
            raise TypeError("frame tuple has the wrong arity")

        def close(self):
            pass

    writer.writer = _TypeErroringWriter()
    # A row the schema accepts, so the failure comes from write_table rather
    # than from building the Arrow arrays.
    writer.buffer = [tuple([0, 0] + [0.0] * (len(writer._schema) - 2))]

    with pytest.raises(TypeError):
        writer._flush_buffer_to_disk()

    assert writer.consecutive_write_failures == 0
    assert writer.write_failed is False


# ─────────────────────────────────────────────────────────────────────────────
# The synchroniser's consumer loop
# ─────────────────────────────────────────────────────────────────────────────


class _NullHardware:
    cpu_usage = 0.0
    voice_db = -60.0
    gpu_usage = -1.0


@pytest.mark.asyncio
async def test_the_consumer_loop_survives_a_bad_batch_and_says_how_many_it_lost(caplog):
    """Broad catch, kept -- but no longer silent.

    If this loop dies the producer keeps pushing into a buffer nothing drains,
    and the session ends reporting frames that were never written. Surviving is
    right; not saying so is what made the survival indistinguishable from
    success.
    """

    class _FailingWriter:
        def __init__(self):
            self.calls = 0

        def push(self, _frame_tuple):
            self.calls += 1
            raise RuntimeError("writer exploded")

    writer = _FailingWriter()
    sync = BiometricSynchronizer(writer=writer, hardware_monitor=_NullHardware(), buffer_size=16)

    sync._buffer.append(("frame",))
    sync._is_running = False  # one pass over what is already buffered, then exit

    await sync._consume_loop()

    assert sync.consume_faults == 1
    assert writer.calls == 1

    with caplog.at_level(logging.CRITICAL, logger="src.core.synchronizer"):
        sync.stop()
    assert any("never reached the writer" in r.message for r in caplog.records)


def test_a_clean_session_says_nothing_about_consumer_faults(caplog):
    """The counterpart. A summary that always prints is a summary nobody reads."""
    sync = BiometricSynchronizer(writer=object(), hardware_monitor=_NullHardware())
    with caplog.at_level(logging.CRITICAL, logger="src.core.synchronizer"):
        sync.stop()
    assert not [r for r in caplog.records if r.levelno >= logging.CRITICAL]


# ─────────────────────────────────────────────────────────────────────────────
# Tracking faults: the audit's actual finding
# ─────────────────────────────────────────────────────────────────────────────


def test_the_first_fault_from_each_source_is_logged_and_the_rest_are_counted(caplog):
    """One log line per source, then a tally.

    At 120 Hz a controller that faults on every frame would otherwise produce
    seven thousand log lines a minute, which is why the original code wrote
    `pass`. Counting is the third option neither of those two offered.
    """
    log = TrackingFaultLog("TestBackend")

    with caplog.at_level(logging.WARNING, logger="src.backends.tracking_faults"):
        for _ in range(5):
            log.record("left_controller", RuntimeError("locate failed"))
        log.record("hmd", RuntimeError("locate failed"))

    assert log.counts["left_controller"] == 5
    assert log.counts["hmd"] == 1
    assert log.total == 6

    first_lines = [r for r in caplog.records if "first this session" in r.message]
    assert len(first_lines) == 2, "one per source, not one per fault"


def test_a_persistently_faulting_source_is_reported_again_at_the_interval(caplog):
    """Bounded, but not silent for the rest of a two-hour session."""
    log = TrackingFaultLog("TestBackend")
    with caplog.at_level(logging.WARNING, logger="src.backends.tracking_faults"):
        for _ in range(REPEAT_LOG_INTERVAL):
            log.record("hmd", RuntimeError("locate failed"))

    assert any("has now failed to track on" in r.message for r in caplog.records)


def test_the_shutdown_summary_reports_faults_as_a_proportion_of_frames(caplog):
    """A count is not actionable; a percentage of the session is."""
    log = TrackingFaultLog("TestBackend")
    for _ in range(250):
        log.record("eye", RuntimeError("gaze unavailable"))

    with caplog.at_level(logging.WARNING, logger="src.backends.tracking_faults"):
        log.summarise(frames_polled=1000)

    summary = [r.message for r in caplog.records if "tracking faults this session" in r.message]
    assert summary, "a session that lost tracking must say so at shutdown"
    assert "eye=250 (25.0% of frames)" in summary[0]


def test_a_session_with_no_faults_summarises_to_silence(caplog):
    """So that a summary appearing at all is itself the signal."""
    log = TrackingFaultLog("TestBackend")
    with caplog.at_level(logging.DEBUG, logger="src.backends.tracking_faults"):
        log.summarise(frames_polled=1000)
    assert caplog.records == []


# ─────────────────────────────────────────────────────────────────────────────
# The engine's boundaries
# ─────────────────────────────────────────────────────────────────────────────


class _UnbindableBackend:
    """A headset that is not plugged in."""

    def initialize(self) -> bool:
        return False

    def poll_frame(self, _frame_index):  # pragma: no cover - never reached
        raise AssertionError("poll_frame must not be reached when binding failed")

    def shutdown(self) -> None:
        pass


def test_a_backend_that_cannot_bind_raises_instead_of_returning(tmp_path):
    """The session's cause of death, made available to its caller.

    `_run_pcvr_mode` used to log an ERROR and `return`, so `start()` completed
    its `finally` and exited normally. A workstation with no headset produced a
    finished session, zero frames, and no stated reason anywhere the API or the
    CLI could reach.
    """
    engine = TelemetryEngine(output_dir=str(tmp_path), gdpr_consent=True)

    with pytest.raises(BackendUnavailableError) as caught:
        engine._run_pcvr_mode(_UnbindableBackend())

    assert "could not bind" in str(caught.value)


def test_a_recording_whose_sink_will_not_open_never_starts(tmp_path):
    """The abort path, end to end, with a stated reason.

    `writer.start()` sits between `hardware.start()` and the acquisition loop.
    It used to be unguarded, so a StorageWriteError travelled to the blanket
    handler at the bottom of `start()` and was logged as one more runtime
    exception -- after the boot sweep had run and with teardown reporting a
    normal session. Now the failure is recognised, named, and nothing after it
    runs.

    The writer is replaced on the instance rather than in the module namespace:
    the object under test owns it, so there is no module attribute to patch and
    no risk of leaking a fake into another test (see the note in
    tests/characterisation/conftest.py about why that matters).
    """
    engine = TelemetryEngine(output_dir=str(tmp_path), gdpr_consent=True)
    assert engine.failure_reason is None

    class _UnopenableWriter:
        def start(self) -> None:
            raise StorageWriteError("Could not open /dev/full for writing: No space left")

        def stop(self) -> None:  # pragma: no cover - must not be reached
            raise AssertionError("teardown ran for a session that never started")

    engine.writer = _UnopenableWriter()
    engine.start()

    assert engine.failure_reason is not None
    assert "storage unavailable" in engine.failure_reason
    assert engine.is_running is False
    assert engine.frames_recorded == 0


# ─────────────────────────────────────────────────────────────────────────────
# The tolerant side: a workstation with nothing attached must still work
# ─────────────────────────────────────────────────────────────────────────────


def test_the_system_profiler_never_raises(monkeypatch):
    """Its callers depend on this contract, so the contract is tested.

    Two callers previously disagreed about whose job the failure was -- one
    wrapped it, one did not -- which is the condition under which a real fault
    is handled by neither.
    """
    import socket

    def _no_hostname():
        raise OSError("name resolution is not available in this sandbox")

    monkeypatch.setattr(socket, "gethostname", _no_hostname)

    profile = collect_system_profile()

    assert profile["hostname"] == "Unknown"
    # The failure of one probe must not cost the others.
    assert profile["os_name"]
    assert profile["python_version"]


def test_one_failing_sync_queue_does_not_stop_the_other_two():
    """Three independent queues, three independent outcomes.

    Written because the obvious refactor -- one try around all three -- is
    wrong, and the shape that makes it wrong is invisible once the handlers are
    collapsed into a loop.
    """

    class _Uploader:
        def retry_pending(self):
            raise ConnectionError("hub unreachable")

        def retry_pending_logs(self):
            return {"attempted": 2, "succeeded": 2}

    class _PatientUploader:
        def retry_pending(self):
            return {"attempted": 1, "succeeded": 1}

    scheduler = BackgroundSyncScheduler(_Uploader(), _PatientUploader(), interval_sec=1.0)
    result = scheduler.sweep_once()

    assert scheduler.sweep_faults == 1
    assert result["sessions"] == {"attempted": 0, "succeeded": 0}, "unchanged from its default"
    assert result["logs"]["succeeded"] == 2
    assert result["patients"]["succeeded"] == 1
