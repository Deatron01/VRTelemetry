# src/core/biosensor_status.py
"""Registry of the latest status heartbeat from each biosensor producer (VRT-36).

Lives on the ``Container``, not on a session's ``TelemetryEngine``: a
researcher needs to see "Polar H10 connected, no skin contact" on the New
Session screen *before* pressing Start, so this has to answer
``GET /api/biosensors/status`` whether or not a recording is running -- it replaced
``NewSession.tsx``'s hardcoded handshake row.

Push, not poll (that doc's §3.2): a producer calls
``POST /api/biosensors/status`` on its own timer, and this class marks an
entry "gone" once its own status stops arriving -- a producer whose process
died must be reported as gone, not as whatever it last reported.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class BiosensorStatusRegistry:
    """Thread-safe last-write-wins store of per-device status reports."""

    def __init__(self, stale_after_sec: float = 90.0) -> None:
        self._lock = threading.Lock()
        self._stale_after_sec = stale_after_sec
        #: device_id -> {**last reported device dict, "producer_id", "_received_monotonic"}
        self._devices: dict[str, dict[str, Any]] = {}

    def report(self, producer_id: str, devices: list[dict[str, Any]]) -> None:
        """Record one producer's heartbeat.

        Replaces the previous report for each ``device_id`` it names.
        Devices it stops naming are left in place rather than deleted --
        they simply age out through the staleness check in :meth:`snapshot`
        -- so a producer that (incorrectly) sends an empty device list on
        one beat does not erase history a UI might be mid-render against.
        """
        now = time.monotonic()
        with self._lock:
            for device in devices:
                device_id = device.get("device_id")
                if not device_id:
                    continue
                self._devices[device_id] = {
                    **device,
                    "producer_id": producer_id,
                    "_received_monotonic": now,
                }

    def snapshot(self) -> list[dict[str, Any]]:
        """Every device this registry has ever heard from, with staleness applied.

        A device whose last report is older than the staleness horizon is
        reported ``connected: false, contact: null, gone: true`` regardless
        of what it last said -- "the producer stopped heartbeating" must
        never be indistinguishable from "the producer's last report was
        good" (host-changes doc, VRT-36's gate).
        """
        now = time.monotonic()
        with self._lock:
            out: list[dict[str, Any]] = []
            for device_id, device in self._devices.items():
                age_sec = now - device["_received_monotonic"]
                gone = age_sec > self._stale_after_sec
                entry = {k: v for k, v in device.items() if not k.startswith("_")}
                entry["device_id"] = device_id
                entry["age_sec"] = round(age_sec, 1)
                if gone:
                    entry["connected"] = False
                    entry["contact"] = None
                    entry["gone"] = True
                else:
                    entry["gone"] = False
                out.append(entry)
            return out
