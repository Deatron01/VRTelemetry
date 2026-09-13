# src/storage/broadcast_sink.py
"""A FrameSink observer that republishes every accepted frame to plugins.

Always used inside a `TeeFrameSink` alongside the real `AsyncParquetWriter`
-- see that module's docstring for why an observer's failure can never affect
recording. Never constructed or used standalone in production.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from src.core.datatypes import FIELD_NAMES

logger = logging.getLogger(__name__)


@runtime_checkable
class FramePublisher(Protocol):
    """What this sink needs from the Event Router, said structurally.

    Deliberately does not import `src.interfaces.api.event_router.EventRouter`:
    `src/storage/` is an inner layer and `src/interfaces/api/` is the outermost
    one, so importing it here would point a dependency the wrong way (see the
    layering note in `src/application/ports.py`, which this Protocol follows
    the same pattern as). `EventRouter` satisfies this shape; nothing here
    needs to know that.
    """

    def publish_frame_threadsafe(self, session_id: str, frame: dict[str, Any]) -> None: ...

    def publish_event_threadsafe(self, event: dict[str, Any]) -> None: ...


class WebSocketBroadcastSink:
    """Adapts `FramePublisher` to the `FrameSink` protocol for one session.

    Runs on `TelemetryEngine`'s private consumer-loop thread (see
    `BiometricSynchronizer._consume_loop`) -- a *different* event loop from
    the one FastAPI serves `/ws/hub/telemetry` connections on.
    `EventRouter.publish_frame_threadsafe` is what bridges the two loops
    (`loop.call_soon_threadsafe`); this class only turns a positional tuple
    back into a named payload and hands it across that bridge. Nothing here
    ever awaits or blocks, matching `FrameSink.push`'s "must be non-blocking"
    contract exactly as `AsyncParquetWriter.push` does.

    `write_failed` is always `False`: zero connected plugins, or an
    unreachable plugin process, is a normal, expected state for this
    application (the same posture as an unreachable central-server hub) --
    never a reason to stop recording frames to disk. Only `TeeFrameSink`'s
    `primary` (the real writer) may ever report `write_failed = True`.
    """

    write_failed = False

    def __init__(self, publisher: FramePublisher, session_id: str) -> None:
        self._publisher = publisher
        self._session_id = session_id

    def start(self) -> None:
        self._publisher.publish_event_threadsafe(
            {"type": "session_start", "session_id": self._session_id}
        )

    def push(self, frame_tuple: tuple[Any, ...]) -> None:
        # zip(..., strict=False): a defensive no-op unless FIELD_NAMES and
        # this tuple's width ever disagree, which would already be a
        # Parquet-corrupting bug elsewhere (see the contract note on
        # TelemetryFrame.to_tuple()) -- this sink must never be where that
        # surfaces as a crash.
        payload = dict(zip(FIELD_NAMES, frame_tuple, strict=False))
        self._publisher.publish_frame_threadsafe(self._session_id, payload)

    def stop(self) -> None:
        self._publisher.publish_event_threadsafe(
            {"type": "session_stop", "session_id": self._session_id}
        )
