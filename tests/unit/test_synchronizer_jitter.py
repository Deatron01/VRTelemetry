"""The oversampling cap must reject floods, not jittered genuine samples.

Regression for the 15 Sep 2026 sessions: the acquisition loop paced itself to
exactly the cap's interval, so a sample arriving a fraction of a millisecond
early was discarded and roughly half of all real samples were lost (60-66 Hz
recorded from a ~120 Hz source).
"""

from src.core.datatypes import TelemetryFrame
from src.core.synchronizer import BiometricSynchronizer


class _Hardware:
    cpu_usage = 0.0
    gpu_usage = 0.0
    voice_db = 0.0


class _Writer:
    write_failed = False


def _sync(max_hz: float = 120.0) -> BiometricSynchronizer:
    return BiometricSynchronizer(writer=_Writer(), hardware_monitor=_Hardware(), max_hz=max_hz)


def _frame(i: int, ts_ns: int) -> TelemetryFrame:
    frame = TelemetryFrame.create_empty(i)
    frame.timestamp_ns = ts_ns
    return frame


def test_slightly_early_sample_is_accepted() -> None:
    sync = _sync(120.0)
    interval = sync.sample_interval_ns
    assert interval is not None
    assert sync.push_frame(_frame(0, 1_000_000_000))
    # 0.2 ms early -- the case that used to be thrown away.
    assert sync.push_frame(_frame(1, 1_000_000_000 + interval - 200_000))
    assert sync.dropped_oversampling == 0


def test_exact_duplicate_is_rejected() -> None:
    sync = _sync(120.0)
    assert sync.push_frame(_frame(0, 5_000_000))
    assert not sync.push_frame(_frame(1, 5_000_000))
    assert sync.dropped_oversampling == 1


def test_burst_inside_half_interval_is_rejected() -> None:
    sync = _sync(120.0)
    interval = sync.sample_interval_ns
    assert interval is not None
    assert sync.push_frame(_frame(0, 0))
    assert not sync.push_frame(_frame(1, interval // 4))
    assert sync.dropped_oversampling == 1


def test_jittered_stream_keeps_nearly_every_sample() -> None:
    """A 120 Hz stream with +/-0.5 ms jitter, paced at a 120 Hz cap."""
    sync = _sync(120.0)
    interval = sync.sample_interval_ns
    assert interval is not None
    jitter = [0, -500_000, 300_000, -200_000, 500_000, -400_000]
    ts = 0
    accepted = 0
    for i in range(600):
        ts_i = ts + jitter[i % len(jitter)]
        if sync.push_frame(_frame(i, ts_i)):
            accepted += 1
        ts += interval
    assert accepted == 600


def test_pacing_interval_is_unchanged() -> None:
    """The loop still paces to the full interval; only rejection loosened."""
    sync = _sync(100.0)
    assert sync.sample_interval_ns == 10_000_000
