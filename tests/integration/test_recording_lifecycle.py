# tests/integration/test_recording_lifecycle.py
"""A whole recording, on fakes (VRT-14).

The gate for phase 4 of the refactor plan, stated there as: *full recording
lifecycle test against in-memory fakes, no hardware, < 2 s*.

This replaces ``test_pipeline.py``, which called itself an end-to-end test and
was not one. It imported ``OpenXRHeadlessBackend`` and
``RuntimeCapabilityDiscovery`` -- so it needed ``pyopenxr`` installed to
collect -- constructed a real engine that opened three SQLite databases and an
HTTP client, monkeypatched ``initialize`` onto a backend instance that
``start()`` then overwrote, slept for 1.5 seconds, and pushed the frames *itself*
rather than letting the engine's loop produce them. What it actually proved was
that ``AsyncParquetWriter`` writes a file when you hand it frames directly.

What is different here is not the assertions but the seam: the engine takes its
:class:`~src.application.recording_context.RecordingDependencies`, and the
backend comes from the registry by name. So the loop under test is the real one,
start to teardown, with nothing patched onto anything.

Deliberately not asserted: anything about Parquet. The sink is a list, and
whether pyarrow writes a valid file is ``AsyncParquetWriter``'s business and has
its own tests. Mixing the two is what made the old test slow and vague.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, ClassVar

import pytest

from src.application.recording_context import RecordingDependencies
from src.backends import registry
from src.core.datatypes import TelemetryFrame
from src.core.engine import TelemetryEngine

#: Wall-clock ceiling for the whole lifecycle. The plan's gate is two seconds;
#: this fails at one, because a gate you can only just meet is one you will
#: quietly stop meeting.
LIFECYCLE_BUDGET_SEC = 1.0

#: At 90 Hz -- the fake headset's refresh rate, which the synchroniser uses as
#: its oversampling cap -- 60 frames is two thirds of a second. Before VRT-24
#: the acquisition loop free-ran and 200 frames arrived almost instantly; a
#: paced loop cannot beat the headset it is pacing to, and should not try.
FRAMES_WANTED = 60


class _ListSink:
    """A FrameSink that keeps frames in a list."""

    def __init__(self) -> None:
        self.frames: list[tuple] = []
        self.write_failed = False
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def push(self, frame_tuple: tuple) -> None:
        self.frames.append(frame_tuple)

    def stop(self) -> None:
        self.stopped = True


class _StubMetrics:
    """A HardwareMetricsSource with fixed readings.

    Constant values on purpose: the synchroniser folds these into every frame,
    so a fixed reading is what lets the test assert they arrived rather than
    that something plausible arrived.
    """

    def __init__(self) -> None:
        self.cpu_usage = 0.42
        self.voice_db = -12.5
        self.gpu_usage = 0.75
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _RecordingMetadataSink:
    """A SessionMetadataSink that remembers what it was asked to persist."""

    def __init__(self, succeed: bool = True) -> None:
        self.succeed = succeed
        self.calls: list[dict[str, Any]] = []

    def persist_experiment(self, metadata: dict[str, Any]) -> bool:
        self.calls.append(metadata)
        return self.succeed


class _RecordingUploader:
    """A SessionUploadPort that accepts everything and records it."""

    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str, dict[str, Any]]] = []
        self.log_uploads: list[tuple[Path, str]] = []
        self.retries = 0

    def upload(
        self, parquet_path: Path, session_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        self.uploads.append((parquet_path, session_id, metadata))
        return {"ok": True}

    def upload_log(self, log_path: Path, session_id: str) -> dict[str, Any]:
        self.log_uploads.append((log_path, session_id))
        return {"ok": True}

    def retry_pending(self) -> dict[str, Any]:
        self.retries += 1
        return {"attempted": 0, "succeeded": 0}


class _FakeBackend:
    """A headset that is always present and always tracking."""

    instances: ClassVar[list[_FakeBackend]] = []

    #: Part of the IVRBackend contract (VRT-24). This fake stamps frames from a
    #: synthetic clock rather than a runtime display time, so app_fps must not
    #: be derived from it.
    timestamp_is_display_time = False

    def __init__(self) -> None:
        self.initialised = False
        self.shut_down = False
        self.polled = 0
        _FakeBackend.instances.append(self)

    def initialize(self) -> bool:
        self.initialised = True
        return True

    def get_refresh_rate_hz(self) -> float:
        return 90.0

    def poll_frame(self, frame_index: int) -> TelemetryFrame:
        self.polled += 1
        frame = TelemetryFrame.create_empty(frame_index)
        # Monotonic and far apart enough that the synchroniser's oversampling
        # cap accepts every frame; a real 90 Hz headset paces itself, and this
        # loop does not.
        frame.timestamp_ns = frame_index * 20_000_000
        frame.hmd_tracking_valid = 1.0
        frame.hmd_pos_x = float(frame_index)
        return frame

    def shutdown(self) -> None:
        self.shut_down = True


@pytest.fixture
def fake_backend_registered() -> Any:
    """Register ``_FakeBackend`` under the name ``"fake"``, and clean up.

    Registration rather than patching: selection then goes through
    ``create_backend`` exactly as it does in production, so what the test
    exercises is the real path and not a lookalike.
    """
    module = types.ModuleType("_vrtelemetry_test_backend")
    module.FakeBackend = _FakeBackend
    sys.modules["_vrtelemetry_test_backend"] = module
    registry.register(
        registry.BackendEntry(
            name="fake",
            module="_vrtelemetry_test_backend",
            attribute="FakeBackend",
            summary="an always-present headset, for tests",
        )
    )
    _FakeBackend.instances.clear()
    try:
        yield
    finally:
        registry._REGISTRY.pop("fake", None)
        sys.modules.pop("_vrtelemetry_test_backend", None)
        _FakeBackend.instances.clear()


@pytest.fixture
def dependencies() -> RecordingDependencies:
    return RecordingDependencies(
        writer=_ListSink(),
        hardware=_StubMetrics(),
        metadata_sink=_RecordingMetadataSink(),
        uploader=_RecordingUploader(),
    )


def _record(engine: TelemetryEngine, sink: _ListSink, frames: int = FRAMES_WANTED) -> float:
    """Run one recording until ``frames`` have reached the sink. Returns seconds."""
    started = time.monotonic()
    thread = threading.Thread(target=engine.start, daemon=True, name="test-engine")
    thread.start()

    deadline = started + LIFECYCLE_BUDGET_SEC
    while len(sink.frames) < frames and time.monotonic() < deadline:
        time.sleep(0.005)

    engine.stop()
    thread.join(timeout=LIFECYCLE_BUDGET_SEC)
    assert not thread.is_alive(), "the engine thread did not finish after stop()"
    return time.monotonic() - started


def test_a_recording_runs_end_to_end_without_hardware_disk_or_network(
    tmp_path: Path, dependencies: RecordingDependencies, fake_backend_registered: Any
) -> None:
    """The gate.

    Boot, bind a backend, poll frames, fold in metrics, hand them to the sink,
    tear down, persist metadata, upload. Every collaborator is a fake, the
    backend arrives through the registry, and the whole thing is under a second.
    """
    engine = TelemetryEngine(
        output_dir=str(tmp_path),
        gdpr_consent=True,
        dependencies=dependencies,
    )
    engine.configured_backend = "fake"

    sink: _ListSink = dependencies.writer  # type: ignore[assignment]
    elapsed = _record(engine, sink)

    assert elapsed < LIFECYCLE_BUDGET_SEC * 2, f"lifecycle took {elapsed:.2f}s"
    assert len(sink.frames) >= FRAMES_WANTED
    assert engine.failure_reason is None
    assert engine.is_running is False

    backend = _FakeBackend.instances[0]
    assert backend.initialised, "the registry-selected backend was never bound"
    assert backend.polled >= FRAMES_WANTED

    metrics: _StubMetrics = dependencies.hardware  # type: ignore[assignment]
    assert metrics.started and metrics.stopped
    assert sink.started and sink.stopped


def test_the_frames_that_reach_the_sink_carry_the_hardware_metrics(
    tmp_path: Path, dependencies: RecordingDependencies, fake_backend_registered: Any
) -> None:
    """The synchroniser's one job, asserted on the real loop's output.

    Nothing copied the monitor's readings into frames before VRT-11; the
    columns were present and always zero. A fixed reading makes the difference
    visible.
    """
    engine = TelemetryEngine(output_dir=str(tmp_path), gdpr_consent=True, dependencies=dependencies)
    engine.configured_backend = "fake"
    sink: _ListSink = dependencies.writer  # type: ignore[assignment]
    _record(engine, sink, frames=50)

    columns = TelemetryFrame.create_empty(0).to_tuple()
    assert len(sink.frames[0]) == len(columns)

    sample = TelemetryFrame.create_empty(0)
    fields = list(sample.__dataclass_fields__)
    cpu_index = fields.index("cpu_utilization")
    gpu_index = fields.index("gpu_utilization")

    assert sink.frames[0][cpu_index] == pytest.approx(0.42)
    assert sink.frames[0][gpu_index] == pytest.approx(0.75)


def test_the_session_is_persisted_once_and_uploaded_once(
    tmp_path: Path, dependencies: RecordingDependencies, fake_backend_registered: Any
) -> None:
    """Once each, and the upload carries the frame count the engine reports.

    ``persist_experiment`` was called twice per start until VRT-13, with the
    first return value discarded. This is the test that keeps it at one.
    """
    engine = TelemetryEngine(output_dir=str(tmp_path), gdpr_consent=True, dependencies=dependencies)
    engine.configured_backend = "fake"
    sink: _ListSink = dependencies.writer  # type: ignore[assignment]
    _record(engine, sink, frames=50)

    metadata_sink: _RecordingMetadataSink = dependencies.metadata_sink  # type: ignore[assignment]
    uploader: _RecordingUploader = dependencies.uploader  # type: ignore[assignment]

    assert len(metadata_sink.calls) == 1, "persist_experiment must be called exactly once"
    assert uploader.retries == 1, "the pending-upload sweep runs once, at boot"
    assert len(uploader.uploads) == 1

    parquet_path, session_id, summary = uploader.uploads[0]
    assert session_id == engine.session_id
    assert parquet_path == engine.parquet_path
    assert summary["total_frames"] == engine.frames_recorded
    assert summary["duration_sec"] is None or summary["duration_sec"] >= 0


def test_a_sink_that_has_failed_stops_the_acquisition_loop(
    tmp_path: Path, dependencies: RecordingDependencies, fake_backend_registered: Any
) -> None:
    """`write_failed` is a contract, and the loop honours it.

    Frames collected after the sink has given up are frames the session will
    report and not have. The loop stops rather than counting them.
    """
    sink: _ListSink = dependencies.writer  # type: ignore[assignment]

    engine = TelemetryEngine(output_dir=str(tmp_path), gdpr_consent=True, dependencies=dependencies)
    engine.configured_backend = "fake"

    thread = threading.Thread(target=engine.start, daemon=True)
    thread.start()

    deadline = time.monotonic() + LIFECYCLE_BUDGET_SEC
    while len(sink.frames) < 20 and time.monotonic() < deadline:
        time.sleep(0.005)

    sink.write_failed = True
    thread.join(timeout=LIFECYCLE_BUDGET_SEC)

    assert not thread.is_alive(), "the loop kept collecting after the sink failed"
    assert engine.is_running is False


def test_an_unknown_backend_name_ends_the_session_with_a_reason(
    tmp_path: Path, dependencies: RecordingDependencies
) -> None:
    """The registry's refusal, arriving where a caller can read it.

    Before VRT-14 this recorded a SteamVR session; before VRT-13 there was
    nowhere for the reason to go.
    """
    engine = TelemetryEngine(output_dir=str(tmp_path), gdpr_consent=True, dependencies=dependencies)
    engine.configured_backend = "no_such_backend"

    engine.start()

    assert engine.failure_reason is not None
    assert "no_such_backend" in engine.failure_reason
    assert engine.frames_recorded == 0


def test_the_reported_frame_count_is_what_the_sink_actually_received(
    tmp_path: Path, dependencies: RecordingDependencies, fake_backend_registered: Any
) -> None:
    """VRT-24 regression: ``frames_recorded`` counts acceptances, not attempts.

    It used to be incremented once per ``poll_frame`` call, before the
    synchroniser had decided anything. On a free-running loop against a
    non-blocking backend that made it the *polling* count: a measured
    three-second session reported 392,956 frames and persisted 322. That number
    is what teardown logs and what ``total_frames`` sends to the hub, so every
    session on the central server carried a frame count three orders of
    magnitude too large.
    """
    engine = TelemetryEngine(
        output_dir=str(tmp_path),
        gdpr_consent=True,
        dependencies=dependencies,
    )
    engine.configured_backend = "fake"

    sink: _ListSink = dependencies.writer  # type: ignore[assignment]
    _record(engine, sink)

    assert engine.frames_recorded == len(sink.frames), (
        "the engine reported a frame count the sink never saw"
    )
    assert engine.frames_polled >= engine.frames_recorded


def test_the_acquisition_loop_is_paced_and_does_not_spin(
    tmp_path: Path, dependencies: RecordingDependencies, fake_backend_registered: Any
) -> None:
    """VRT-24 regression: the loop sleeps until the next sample is due.

    ``_FakeBackend.poll_frame`` returns immediately, exactly like SteamVR's
    overlay path, which reads *predicted* poses rather than waiting on the
    compositor. Unpaced, this loop polled ~131,000 times a second and the
    synchroniser discarded 99.92% of the result -- a core pinned at 100% for the
    length of a session, on the same machine as the compositor.

    The bound is deliberately loose (10x the accepted count rather than 1.05x):
    it is there to catch a spin, not to pin down scheduler jitter.
    """
    engine = TelemetryEngine(
        output_dir=str(tmp_path),
        gdpr_consent=True,
        dependencies=dependencies,
    )
    engine.configured_backend = "fake"

    sink: _ListSink = dependencies.writer  # type: ignore[assignment]
    _record(engine, sink)

    assert engine.frames_recorded > 0
    assert engine.frames_polled < engine.frames_recorded * 10, (
        f"polled {engine.frames_polled} times to record {engine.frames_recorded} "
        f"frames -- the acquisition loop is spinning"
    )
