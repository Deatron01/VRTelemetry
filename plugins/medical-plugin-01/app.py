# plugins/medical-plugin-01/app.py
"""Plugin 01 -- medical/psychometric analytics, running out-of-process.

Subscribes to the Core Hub's Event Router (`/ws/hub/telemetry` -- *not* the
multi-workstation `central_server` hub; see the naming note at the top of
`src/interfaces/api/event_router.py`) and does the analysis work that used to
run inside the Core Hub's process.

## What moved here, and what deliberately did not

**Moved:** SSQ and NASA-TLX scoring (`ssq_nasa_tlx.py`, relocated unmodified
from `src/analytics/questionnaires.py`) and a per-session biometric summary.
Both are pure computation over data the Core Hub already decided to record
-- nothing here is a precondition for recording, so running it
out-of-process, possibly late, possibly not at all if this plugin is down,
changes nothing about data safety.

**Did NOT move: GDPR consent enforcement.** `src/patients/` and
`src/application/consent.py` stay in the Core Hub, unchanged. This plugin
finds out about a session only via a WebSocket message the Hub chooses to
send, *after* `POST /api/recording/start` has already decided to record --
a gate that runs after the decision it's supposed to gate is not a gate. See
the plan doc's "Why consent enforcement cannot become a plugin" for the full
reasoning. This plugin only *reads* the consent id the Hub already validated
(carried on `session_start`), so its own output can be traced back to the
consent record it was produced under -- it never decides whether recording
happens.

This plugin is a subscriber, never a dependency: if it is not running, not
installed, or it crashes, telemetry recording is completely unaffected --
see `src/storage/tee_sink.py`'s docstring in the Core Hub for the mechanism
that guarantees this.

Run standalone for development:

    python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
    set HUB_WS_URL=ws://127.0.0.1:8000/ws/hub/telemetry
    .venv/Scripts/python app.py

In production this is launched by `PluginManager`
(`src/plugin_manager/manager.py`), which sets `HUB_WS_URL` and
`HUB_PLUGIN_TOKEN` for you from `registry.json` and the Core Hub's own
configuration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import websockets
from ssq_nasa_tlx import score_nasa_tlx, score_ssq
from stress_inference import StressInferenceUnavailableError, summarize_session

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s medical-plugin-01 %(levelname)s %(message)s"
)
logger = logging.getLogger("medical_plugin_01")

OUTPUT_DIR = Path(os.environ.get("PLUGIN_OUTPUT_DIR", "output"))


class SessionAggregate:
    """Running biometric summary for one session. O(1) memory regardless of
    session length -- this plugin never buffers raw frames."""

    __slots__ = ("_boundary_min", "_hr_n", "_hr_sum", "consent_id", "frame_count", "session_id")

    def __init__(self, session_id: str, consent_id: str | None) -> None:
        self.session_id = session_id
        self.consent_id = consent_id
        self.frame_count = 0
        self._hr_sum = 0.0
        self._hr_n = 0
        self._boundary_min = float("inf")

    def observe(self, frame: dict[str, Any]) -> None:
        self.frame_count += 1
        hr = frame.get("heart_rate_bpm")
        if hr is not None and hr > 0:
            self._hr_sum += hr
            self._hr_n += 1
        boundary = frame.get("distance_to_boundary")
        if boundary is not None and boundary >= 0:
            self._boundary_min = min(self._boundary_min, boundary)

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "consent_id": self.consent_id,
            "frame_count": self.frame_count,
            "mean_heart_rate_bpm": (self._hr_sum / self._hr_n) if self._hr_n else None,
            "min_distance_to_boundary": (
                None if self._boundary_min == float("inf") else self._boundary_min
            ),
        }


class MedicalPlugin:
    def __init__(self, hub_ws_url: str, token: str | None) -> None:
        self._hub_ws_url = hub_ws_url
        self._token = token
        self._sessions: dict[str, SessionAggregate] = {}

    def _connect_url(self) -> str:
        url = self._hub_ws_url
        params = []
        if self._token:
            params.append(f"token={self._token}")
        params.append("plugin_id=medical-analytics-01")
        sep = "&" if "?" in url else "?"
        return url + sep + "&".join(params)

    async def run(self) -> None:
        url = self._connect_url()
        backoff = 1.0
        while True:
            try:
                logger.info(f"Connecting to Core Hub at {self._hub_ws_url}...")
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("Connected. Listening for telemetry and questionnaire events.")
                    backoff = 1.0
                    async for raw in ws:
                        self._handle(json.loads(raw))
            except (websockets.WebSocketException, OSError) as exc:
                logger.warning(f"Hub connection lost ({exc}); reconnecting in {backoff:.0f}s.")
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    def _handle(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type == "session_start":
            session_id = message["session_id"]
            self._sessions[session_id] = SessionAggregate(session_id, message.get("consent_id"))
            logger.info(f"Session {session_id} started.")
        elif msg_type == "telemetry_frame":
            aggregate = self._sessions.get(message["session_id"])
            if aggregate is not None:
                aggregate.observe(message["frame"])
        elif msg_type == "session_stop":
            aggregate = self._sessions.pop(message["session_id"], None)
            if aggregate is not None:
                self._finalize(aggregate)
        elif msg_type == "questionnaire_submitted":
            self._score_questionnaire(message)
        else:
            logger.debug(f"Ignoring unrecognised event type {msg_type!r}.")

    def _finalize(self, aggregate: SessionAggregate) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        summary = aggregate.summary()
        try:
            summary["stress_inference"] = summarize_session(summary)
        except StressInferenceUnavailableError as exc:
            # Deliberately not implemented -- see stress_inference.py.
            # Recorded as an explicit "not available", never a fabricated number.
            summary["stress_inference"] = {"available": False, "reason": str(exc)}

        out_path = OUTPUT_DIR / f"{aggregate.session_id}_biometric_summary.json"
        out_path.write_text(json.dumps(summary, indent=2))
        logger.info(
            f"Session {aggregate.session_id} finished ({aggregate.frame_count} frames) -> {out_path}"
        )

    def _score_questionnaire(self, message: dict[str, Any]) -> None:
        instrument = message.get("instrument")
        items = message.get("items", {})
        if instrument == "ssq":
            scored = score_ssq(items)
        elif instrument == "nasa_tlx":
            scored = score_nasa_tlx(items)
        else:
            logger.warning(f"Unknown questionnaire instrument {instrument!r}; ignoring.")
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        session_id = message.get("session_id", "unknown")
        out_path = OUTPUT_DIR / f"{session_id}_{instrument}.json"
        out_path.write_text(json.dumps(scored, indent=2))
        logger.info(f"Scored {instrument} for session {session_id} -> {out_path}")


def main() -> None:
    hub_ws_url = os.environ.get("HUB_WS_URL", "ws://127.0.0.1:8000/ws/hub/telemetry")
    token = os.environ.get("HUB_PLUGIN_TOKEN")
    plugin = MedicalPlugin(hub_ws_url, token)
    try:
        asyncio.run(plugin.run())
    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl+C).")


if __name__ == "__main__":
    main()
