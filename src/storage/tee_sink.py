# src/storage/tee_sink.py
"""Fan one authoritative FrameSink out to observers, invisibly to everyone above it.

Part of the VR Telemetry Hub / plugin architecture (see
`claude/vr-telemetry-hub-plugin-architecture-plan.md`). This is the seam that
lets the Event Router see every frame without `BiometricSynchronizer` or
`TelemetryEngine` knowing plugins exist at all.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TeeFrameSink:
    """Wraps one authoritative `FrameSink` (`src.application.ports.FrameSink`)
    with zero or more observers, and implements the same three-method
    contract itself -- so it drops into `RecordingDependencies.writer` /
    `BiometricSynchronizer` with no change to either. The synchroniser's
    consumer loop calls `writer.push(...)` once per accepted frame and has no
    way to tell it is talking to more than one sink.

    The asymmetry is deliberate and is the whole point of this class:

    * `primary` (in production, `AsyncParquetWriter`) decides `write_failed`.
      A `True` here is what stops acquisition in
      `TelemetryEngine._run_pcvr_mode` -- see that method's `writer.write_failed`
      check -- so only a real disk-write failure may do that.
    * An **observer** (in production, `WebSocketBroadcastSink`) can raise,
      block briefly, or simply have nothing listening on the other end, and
      none of that may ever propagate: every observer call is wrapped and
      logged here. A plugin subsystem being down is the same kind of ordinary
      condition as an unreachable central-server hub -- not a reason to lose
      a frame that already reached disk, and never a reason to stop
      recording one.

    This mirrors, at the frame level, the same posture
    `Container.__post_init__` states at the HTTP-client level: exactly one
    thing is allowed to be "the" authority, and everything else is additive.
    """

    def __init__(self, primary: Any, *observers: Any) -> None:
        self._primary = primary
        self._observers = tuple(observers)

    @property
    def write_failed(self) -> bool:
        return bool(self._primary.write_failed)

    def start(self) -> None:
        self._primary.start()
        for observer in self._observers:
            try:
                observer.start()
            except Exception:
                logger.exception(
                    f"Frame sink observer {observer!r} failed to start; continuing without it."
                )

    def push(self, frame_tuple: tuple[Any, ...]) -> None:
        self._primary.push(frame_tuple)
        for observer in self._observers:
            try:
                observer.push(frame_tuple)
            except Exception:
                logger.exception(
                    f"Frame sink observer {observer!r} failed on push; dropped this frame for it only "
                    f"(the primary sink already has it)."
                )

    def stop(self) -> None:
        # Observers first: a plugin broadcaster's stop() sends a "session_stop"
        # event, which reads better to a subscriber before the primary sink's
        # own (synchronous, potentially slower) flush-and-seal. Order has no
        # effect on `write_failed`, which only ever reflects `primary`.
        for observer in self._observers:
            try:
                observer.stop()
            except Exception:
                logger.exception(
                    f"Frame sink observer {observer!r} failed to stop; continuing teardown."
                )
        self._primary.stop()
