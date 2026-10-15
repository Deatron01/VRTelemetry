# src/interfaces/api/routers/biosensors.py
"""The biosensor ingest API (VRT-32..36).

Normative contract: ``plugins/BIOSENSOR_INGEST.md``. Design rationale:
``claude/vrtelemetry-biosensor-host-changes.md``. This is the "generic
escape hatch" described there -- any third-party device that can POST JSON
with a bearer token integrates directly, with or without a sensor-plugin
process in between.

The one invariant this router exists to protect, borrowed verbatim from the
sensor plugin's own founding document
(``biosensor-plugin-project-plan.md``, "the plugin must never fail, slow,
or stop the telemetry recording it runs alongside"): the *host* side of that
contract is that ingest must never raise into, block, or otherwise touch
the acquisition/consumer threads that own the actual recording. See
``TelemetryEngine.ingest_biosensor_sample`` for where that isolation is
actually enforced -- this router's job is auth, session resolution, and
translating the wire format into that call.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from src.config import Settings
from src.interfaces.api.dependencies import (
    BiosensorStatusDep,
    BiosensorStreamsDep,
    RecordingDep,
    SettingsDep,
)
from src.interfaces.api.schemas.biosensors import (
    BiosensorSampleBatch,
    BiosensorSampleResult,
    BiosensorStatusReport,
    BiosensorStatusSnapshot,
)
from src.utils.clock import utc_now_iso
from src.utils.logger import logger

router = APIRouter(tags=["biosensors"])


def _check_token(settings: Settings, authorization: str | None) -> None:
    """Bearer-token auth (BIOSENSOR_INGEST.md, "Auth", rule 4: "the token is required").

    Unlike ``/ws/hub/telemetry``'s ``PluginBusSettings.shared_token`` (which
    defaults to open, tolerable only behind loopback), an unconfigured token
    here disables ingest outright rather than accepting unauthenticated
    writes into a research record -- see that rule for why the two
    endpoints are allowed to disagree.
    """
    token = settings.biosensor.shared_token
    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Biosensor ingest is not configured: set "
                "VRT_BIOSENSOR__SHARED_TOKEN (or [biosensor] shared_token in "
                "config.toml) before a sensor plugin can write samples."
            ),
        )
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token.")


@router.post("/api/biosensors/sample", response_model=BiosensorSampleResult)
def ingest_sample(
    payload: BiosensorSampleBatch,
    recording: RecordingDep,
    settings: SettingsDep,
    biosensor_streams: BiosensorStreamsDep,
    authorization: str | None = Header(default=None),
) -> BiosensorSampleResult:
    _check_token(settings, authorization)

    engine = recording.engine
    if engine is None or not recording.is_running or engine.session_id != payload.session_id:
        # "Unknown or finished session_id -> drop and count. Not a 4xx that
        # makes a plugin retry forever." (BIOSENSOR_INGEST.md, rule 3.)
        return BiosensorSampleResult(accepted=0, dropped=len(payload.samples))

    max_batch = settings.biosensor.max_samples_per_request
    samples = payload.samples[:max_batch]
    overflow_dropped = len(payload.samples) - len(samples)

    accepted = 0
    channels_seen: set[str] = set()
    for sample in samples:
        try:
            engine.ingest_biosensor_sample(
                device_id=payload.device_id,
                channel=sample.channel,
                value=sample.value,
                quality=sample.quality,
                t_wall_ns=sample.t_wall_ns,
            )
            accepted += 1
            channels_seen.add(sample.channel)
        except Exception:  # noqa: BLE001 - ingest must never fail the request or the recording
            logger.exception(
                f"Biosensor sample from device {payload.device_id!r} dropped due to an "
                f"unexpected ingest error."
            )

    dropped = (len(samples) - accepted) + overflow_dropped

    try:
        biosensor_streams.record_batch(
            session_id=payload.session_id,
            device_id=payload.device_id,
            producer_id=None,
            channels=channels_seen,
            accepted=accepted,
            dropped=dropped,
            received_at_utc=utc_now_iso(),
        )
    except Exception:  # noqa: BLE001 - provenance bookkeeping must never fail the ingest response
        logger.exception("Failed to record biosensor_streams provenance row.")

    return BiosensorSampleResult(accepted=accepted, dropped=dropped)


@router.post("/api/biosensors/status")
def report_status(
    payload: BiosensorStatusReport,
    biosensor_status: BiosensorStatusDep,
    settings: SettingsDep,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(settings, authorization)
    biosensor_status.report(
        payload.producer_id, [device.model_dump() for device in payload.devices]
    )
    return {"ok": True}


@router.get("/api/biosensors/status", response_model=BiosensorStatusSnapshot)
def get_status(biosensor_status: BiosensorStatusDep) -> BiosensorStatusSnapshot:
    """Unauthenticated on purpose: this is what ``NewSession.tsx`` polls
    before a recording starts (the desktop UI, not a plugin, is the caller),
    and it discloses connection status only -- no participant or sample
    data.
    """
    return BiosensorStatusSnapshot(devices=biosensor_status.snapshot())
