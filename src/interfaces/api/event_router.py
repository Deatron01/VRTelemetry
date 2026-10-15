# src/interfaces/api/event_router.py
"""The real-time plugin bus: WebSocket fan-out of live telemetry & events.

## Naming -- read this before renaming anything

This project already has a "hub": `src/central_server`, the separate
multi-workstation sync/licensing service described in the README
(`GET /health`, `VRT_HUB__*` settings, `HubSettings`). That hub is a different machine, a different
process, and this file has nothing to do with it.

The "VR Telemetry Hub" in the plugin-architecture request is a different
concept: this workstation's own API process, extended so out-of-process
*plugins* (a medical-analytics service, a ROS 2 bridge) can subscribe to its
live telemetry. To avoid a second thing answering to "the hub," this module
is called the **Event Router** everywhere in code, logs and settings; "Core
Hub" is fine in conversation and docs as long as it is never typed as
`Hub`/`hub_*` next to the existing one. See the plan doc's naming section for
the full reasoning.

## What this is

`EventRouter` owns every plugin WebSocket connection
(`/ws/hub/telemetry`) and fans out two kinds of message:

* **Frames**, pushed from `WebSocketBroadcastSink` on `TelemetryEngine`'s
  private consumer-loop thread, up to 120 Hz.
* **Events** (`session_start`, `session_stop`, and anything else the API
  process wants plugins to know -- e.g. a future `questionnaire_submitted`),
  pushed from that same sink or from a request handler on the API's own loop.

Both go through `publish_frame_threadsafe` / `publish_event_threadsafe`,
safe to call from *any* thread. Neither blocks: the payload is handed to this
router's own event loop with `loop.call_soon_threadsafe` and the caller
returns immediately, whether zero, one or many plugins are connected, and
whether they are keeping up or not. A plugin that falls behind has its
per-connection queue capped (`max_queue_per_client`); once full, the
*oldest* queued item is dropped in favour of the newest one, because for
live telemetry the newest sample is what matters -- the opposite rule from
the Parquet path, which must never drop a frame silently (see
`TeeFrameSink`'s docstring for why the two paths differ on purpose).

## What this is not

Not a persistence layer, not an authority on anything, and not in the
recording's critical path. See `TeeFrameSink` and `WebSocketBroadcastSink`
for the mechanism that keeps it that way: if this router (or every plugin
connected to it) crashed outright, `TelemetryEngine` would keep recording to
Parquet exactly as it does today, because `write_failed` never reflects
anything that happens in this file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from src.core.plugin_protocol import PROTOCOL_VERSION

logger = logging.getLogger(__name__)

#: Re-exported for anything that imported it from here before it moved to
#: `src.core.plugin_protocol` (its single source of truth, shared with
#: `src.plugin_manager.manifest`'s plugin.json validation -- see that
#: module's docstring for why it lives in `src.core` rather than here).
#: Every published message carries this under `"protocol_version"` so a
#: plugin can refuse to misinterpret a version it wasn't written against,
#: instead of silently mis-parsing it -- the same failure class the
#: FIELD_NAMES self-check in `src/core/datatypes.py` exists to catch on the
#: Hub's own side.
__all__ = ["PROTOCOL_VERSION", "EventRouter"]


@dataclass
class _PluginConnection:
    websocket: WebSocket
    plugin_id: str
    queue: asyncio.Queue[dict[str, Any]]
    sender_task: asyncio.Task[None] | None = None
    dropped: int = 0
    connected_at: float = field(default_factory=time.time)


class EventRouter:
    """See module docstring. One instance per `Container` (one per app)."""

    def __init__(
        self,
        *,
        shared_token: str | None = None,
        max_queue_per_client: int = 240,
    ) -> None:
        #: Required as a `?token=` query param or `X-Plugin-Token` header on
        #: connect when set. `None` (the default) means the endpoint is open
        #: to anything that can reach it -- acceptable only because the
        #: workstation API itself binds to loopback by default (README §02);
        #: set a token via settings before ever exposing this
        #: process beyond loopback.
        self._shared_token = shared_token
        #: ~2 seconds of buffer at 120 Hz. Deliberately small: a plugin this
        #: far behind needs the newest frame, not a queue of stale ones.
        self._max_queue_per_client = max_queue_per_client

        self._loop: asyncio.AbstractEventLoop | None = None
        self._connections: dict[str, _PluginConnection] = {}
        self._next_anon_id = 0

        self.router = APIRouter()
        self.router.add_api_websocket_route("/ws/hub/telemetry", self._telemetry_endpoint)

    # --- lifecycle -----------------------------------------------------

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop plugin WebSocket connections are served on.

        Call once, from the FastAPI app's `lifespan`
        (`asyncio.get_running_loop()`), before any recording can start.
        `publish_*_threadsafe` logs and drops rather than raising if this was
        never called -- see that method's docstring for why: it is called
        from the acquisition path via `TeeFrameSink`, which must never let an
        observer's fault reach the recording loop.
        """
        self._loop = loop

    # --- producer-facing API (call from ANY thread) ----------------------

    def publish_frame_threadsafe(self, session_id: str, frame: dict[str, Any]) -> None:
        self._publish_threadsafe(
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "telemetry_frame",
                "session_id": session_id,
                "frame": frame,
            }
        )

    def publish_event_threadsafe(self, event: dict[str, Any]) -> None:
        # `event` first, `protocol_version` second: a caller is free to pass
        # its own value in `event` (it won't -- nothing in this codebase
        # does -- but a plugin's own tooling might replay a captured message)
        # and the router's own version is what a live connection is actually
        # governed by, so it must win rather than be silently shadowed.
        self._publish_threadsafe({**event, "protocol_version": PROTOCOL_VERSION})

    def _publish_threadsafe(self, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            # A wiring bug (bind_loop was never called), not a runtime
            # condition -- but this is reached from TeeFrameSink's observer
            # call, which is caught and logged one level up regardless. Still
            # returns rather than raising, so a bug here reads as "no
            # plugins ever receive anything," never as a recording fault.
            logger.error("EventRouter.publish called before bind_loop(); dropping payload.")
            return
        loop.call_soon_threadsafe(self._fan_out_nowait, payload)

    def _fan_out_nowait(self, payload: dict[str, Any]) -> None:
        """Runs on the router's own loop, scheduled via `call_soon_threadsafe`.
        Never awaits -- every connection's queue is a `put_nowait`."""
        for conn in list(self._connections.values()):
            try:
                conn.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop oldest, keep newest -- see __init__'s docstring on
                # max_queue_per_client.
                try:
                    conn.queue.get_nowait()
                    conn.queue.put_nowait(payload)
                except (
                    asyncio.QueueEmpty
                ):  # pragma: no cover - queue can't empty between the two calls above
                    pass
                conn.dropped += 1

    # --- convenience: build a session's broadcast sink -------------------

    def frame_sink_for_session(self, session_id: str) -> Any:
        """A `FrameSink` that republishes this session's frames to plugins.

        Function-local import: `src.storage` is an inner layer and this
        module is the outermost one, so the dependency points the normal
        direction (outer -> inner) and only needs to resolve at call time,
        matching the composition-root convention already used in
        `src/application/recording_context.py`.
        """
        from src.storage.broadcast_sink import WebSocketBroadcastSink

        return WebSocketBroadcastSink(self, session_id)

    # --- connection handling ---------------------------------------------

    async def _telemetry_endpoint(self, websocket: WebSocket) -> None:
        if self._shared_token is not None:
            token = websocket.query_params.get("token") or websocket.headers.get("x-plugin-token")
            if token != self._shared_token:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

        await websocket.accept()
        plugin_id = websocket.query_params.get("plugin_id") or self._anon_id()
        conn = _PluginConnection(
            websocket=websocket,
            plugin_id=plugin_id,
            queue=asyncio.Queue(maxsize=self._max_queue_per_client),
        )
        conn.sender_task = asyncio.ensure_future(self._sender_loop(conn))
        self._connections[plugin_id] = conn
        logger.info(f"Plugin '{plugin_id}' connected to the telemetry event router.")

        try:
            while True:
                # Inbound messages are not part of the v1 contract -- plugins
                # subscribe, they do not publish back into the recording.
                # This loop exists only to notice a disconnect promptly,
                # which `receive_text` does by raising WebSocketDisconnect.
                message = await websocket.receive_text()
                logger.debug(
                    f"Ignoring inbound message from plugin '{plugin_id}': {message[:200]!r}"
                )
        except WebSocketDisconnect:
            pass
        finally:
            self._connections.pop(plugin_id, None)
            if conn.sender_task is not None:
                conn.sender_task.cancel()
            logger.info(
                f"Plugin '{plugin_id}' disconnected "
                f"({conn.dropped} frame(s) dropped for backpressure while connected)."
            )

    async def _sender_loop(self, conn: _PluginConnection) -> None:
        try:
            while True:
                payload = await conn.queue.get()
                await conn.websocket.send_text(json.dumps(payload, default=str))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                f"Plugin '{conn.plugin_id}' sender loop failed; connection will be dropped."
            )

    def _anon_id(self) -> str:
        self._next_anon_id += 1
        return f"anon-{self._next_anon_id}"

    # --- introspection (wire to a GET /api/plugins/status route if wanted) -

    def connected_plugins(self) -> list[dict[str, Any]]:
        return [
            {
                "plugin_id": conn.plugin_id,
                "connected_at": conn.connected_at,
                "dropped": conn.dropped,
                "queue_depth": conn.queue.qsize(),
            }
            for conn in self._connections.values()
        ]
