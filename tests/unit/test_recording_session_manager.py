"""The recording manager's stated contract (VRT-12).

What this replaces was two module-level globals::

    active_engine = None
    engine_thread = None

read by six route handlers and written by one, with no synchronisation
whatsoever. FastAPI runs synchronous handlers on a threadpool, so those reads
and writes genuinely were concurrent -- it simply never bit, because a
researcher presses Start once and then goes and fits the headset. "Has not
happened yet" is not a contract, and it is not something a reader of the code
could have checked.

:class:`~src.interfaces.api.container.RecordingSessionManager` states the
contract in its docstring. These tests are what make the docstring true.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.interfaces.api.container import RecordingSessionManager


class _FakeEngine:
    """The two attributes the manager actually touches, and nothing else.

    A real ``TelemetryEngine`` opens a Parquet writer, a hardware monitor and a
    VR backend. None of that is relevant to whether one recording at a time is
    enforced, and requiring a headset to test the lock is how the lock ends up
    untested.
    """

    def __init__(self, *, running: bool = True) -> None:
        self.is_running = running
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_running = False


def _noop(_engine: Any) -> None:
    """A thread target that finishes immediately."""


def test_a_fresh_manager_has_nothing_running() -> None:
    manager = RecordingSessionManager()

    assert manager.engine is None
    assert manager.is_running is False


def test_start_publishes_the_engine_before_the_thread_runs() -> None:
    """The live-state routes must never observe a half-started recording.

    ``/api/session/scene`` and its three siblings can be hit the instant the
    start handler returns. If the engine were published after the thread
    started, there would be a window in which a recording was running and the
    routes that steer it returned 400.
    """
    manager = RecordingSessionManager()
    engine = _FakeEngine()
    seen: list[Any] = []

    thread = manager.start(engine, lambda _e: seen.append(manager.engine))
    thread.join(timeout=5)

    assert manager.engine is engine
    assert seen == [engine], "the thread ran before the engine was visible"


def test_the_engine_thread_is_a_daemon() -> None:
    """A researcher closing the app must not wait on an acquisition loop.

    The loop can be mid-frame, and mid-frame can mean blocked on a UDP read
    from a headset that has already been taken off and switched off.
    """
    manager = RecordingSessionManager()

    thread = manager.start(_FakeEngine(), _noop)

    assert thread.daemon is True


def test_start_refuses_a_second_recording() -> None:
    """One recording per process, enforced rather than assumed.

    Previously the second start overwrote the first engine's reference. The
    first recording carried on writing frames with nothing left able to stop
    it, and the researcher had two sessions interleaved in one file.
    """
    manager = RecordingSessionManager()
    first = _FakeEngine()
    manager.start(first, _noop).join(timeout=5)

    with pytest.raises(RuntimeError, match="already running"):
        manager.start(_FakeEngine(), _noop)

    assert manager.engine is first


def test_start_is_allowed_again_once_the_engine_reports_it_stopped() -> None:
    manager = RecordingSessionManager()
    first = _FakeEngine()
    manager.start(first, _noop).join(timeout=5)
    manager.stop()

    second = _FakeEngine()
    manager.start(second, _noop).join(timeout=5)

    assert manager.engine is second


def test_stop_signals_the_engine_and_reports_that_it_did() -> None:
    manager = RecordingSessionManager()
    engine = _FakeEngine()
    manager.start(engine, _noop).join(timeout=5)

    stopped = manager.stop()

    assert stopped is True
    assert engine.stop_calls == 1
    assert manager.is_running is False


def test_stop_with_nothing_running_reports_false_rather_than_raising() -> None:
    """The route turns this into its 400; the manager does not decide policy."""
    assert RecordingSessionManager().stop() is False


def test_stop_does_not_hold_the_lock_while_the_engine_tears_down() -> None:
    """Teardown flushes the writer and joins threads. It is not instant.

    Holding the lock across it would block every status read for the duration
    -- including the heartbeat's, which is what tells the admin UI this
    workstation is alive. A researcher would see the workstation go dark for
    exactly as long as the file took to flush.
    """
    manager = RecordingSessionManager()
    observed: list[bool] = []
    release = threading.Event()

    class _SlowEngine(_FakeEngine):
        def stop(self) -> None:
            # Read the manager's state from another thread while this teardown
            # is in progress. If stop() held the lock, this would deadlock and
            # the join below would time out.
            reader = threading.Thread(target=lambda: observed.append(manager.is_running))
            reader.start()
            reader.join(timeout=5)
            release.set()
            super().stop()

    manager.start(_SlowEngine(), _noop).join(timeout=5)
    manager.stop()

    assert release.is_set(), "stop() deadlocked against its own lock"
    assert observed == [True]


def test_concurrent_starts_produce_exactly_one_recording() -> None:
    """Eight threads racing the way Starlette's threadpool actually can.

    Without the lock this is the failure mode: several engines constructed,
    several threads started, one reference kept, the rest orphaned and still
    writing. With it, exactly one wins and the other seven get the RuntimeError
    the route turns into a 400.
    """
    manager = RecordingSessionManager()
    engines = [_FakeEngine() for _ in range(8)]
    started: list[Any] = []
    refused: list[Exception] = []
    barrier = threading.Barrier(len(engines))
    lock = threading.Lock()

    def attempt(engine: _FakeEngine) -> None:
        barrier.wait(timeout=5)
        try:
            manager.start(engine, _noop)
            with lock:
                started.append(engine)
        except RuntimeError as exc:
            with lock:
                refused.append(exc)

    threads = [threading.Thread(target=attempt, args=(e,)) for e in engines]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(started) == 1, f"{len(started)} recordings started concurrently"
    assert len(refused) == len(engines) - 1
    assert manager.engine is started[0]


def test_is_running_follows_the_engine_rather_than_the_manager() -> None:
    """The engine decides when it has finished, not the manager.

    The acquisition loop can end on its own -- the headset disconnects, the
    backend raises -- without anything calling stop(). The manager must report
    that rather than insisting a recording is still in flight.
    """
    manager = RecordingSessionManager()
    engine = _FakeEngine()
    manager.start(engine, _noop).join(timeout=5)
    assert manager.is_running is True

    engine.is_running = False  # the loop ended on its own
    time.sleep(0)

    assert manager.is_running is False
    assert manager.engine is engine, "the engine stays readable after it stops"
