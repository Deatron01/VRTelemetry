# src/interfaces/api/schemas/biosensors.py
"""Request/response models for the biosensor ingest API (VRT-32..36).

Normative contract lives in ``plugins/BIOSENSOR_INGEST.md``; these models are
its implementation, not a second source of truth -- if the two disagree, the
markdown wins (per that file's own header) and this module should be
brought back in line with it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BiosensorSample(BaseModel):
    #: Producer's ``time.time_ns()`` at arrival -- wall clock, never a
    #: monotonic clock (BIOSENSOR_INGEST.md, "Sample ingest", rule 2).
    t_wall_ns: int
    channel: str
    value: float
    #: 0.0-1.0, or ``None`` ("unknown") -- never assumed 1.0 from a missing value.
    quality: float | None = None


class BiosensorSampleBatch(BaseModel):
    session_id: str
    device_id: str
    samples: list[BiosensorSample] = Field(default_factory=list)


class BiosensorSampleResult(BaseModel):
    accepted: int
    dropped: int


class BiosensorDeviceStatus(BaseModel):
    device_id: str
    display_name: str | None = None
    transport: str | None = None
    connected: bool = False
    contact: bool | None = None
    link_quality: float | None = None
    last_sample_age_ms: float | None = None
    channels: list[str] = Field(default_factory=list)


class BiosensorStatusReport(BaseModel):
    producer_id: str
    devices: list[BiosensorDeviceStatus] = Field(default_factory=list)


class BiosensorStatusSnapshot(BaseModel):
    devices: list[dict[str, Any]] = Field(default_factory=list)
