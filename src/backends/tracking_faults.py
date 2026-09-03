# src/backends/tracking_faults.py
"""Counting the tracking failures a backend survives (VRT-13).

The audit's finding about this codebase's error handling was not that it
crashed. It was the opposite::

    62 blanket `except Exception` handlers, concentrated in acquisition --
    a session that lost tracking is indistinguishable from a clean one in
    the dataset.

Every VR backend polls several independent sources per frame: the headset, each
controller, the eye tracker. A source that fails to locate leaves its columns at
the zeros ``TelemetryFrame.create_empty`` set and its ``*_tracking_valid`` flag
at 0.0, which is *correct* -- those are the same values a controller that is
switched off produces, because from the data's point of view the two are the
same thing.

They are not the same thing for the researcher. "The subject put the controller
down" and "the runtime returned an error for the controller on 40% of frames"
produce identical Parquet files and identical logs, and the second one is a
result that should not be published.

So the handlers stay -- one bad locate must not end a recording -- but they stop
being silent. Each fault is attributed to a named source and counted; the first
of each kind is logged, and :meth:`TrackingFaultLog.summarise` reports the
totals at shutdown, where the researcher sees them next to the frame count.

This module deliberately imports nothing from ``xr`` or ``openvr``: it is
counting, and the unit tests must be able to import it on a machine with no VR
runtime installed.
"""

from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)

#: How many faults from one source pass before the log says so again. One frame
#: in ~1000 is roughly eight seconds of a 120 Hz session, which is often enough
#: to notice a session going wrong while it is still running and rare enough not
#: to drown the acquisition log.
REPEAT_LOG_INTERVAL = 1000


class TrackingFaultLog:
    """Per-source tally of tracking failures within one session.

    Args:
        backend_name: Named in every message, because a session that fell back
            from one backend to another otherwise produces two indistinguishable
            sets of counts.
    """

    def __init__(self, backend_name: str) -> None:
        self.backend_name = backend_name
        self.counts: Counter[str] = Counter()

    def record(self, source: str, exc: BaseException) -> None:
        """Attribute one fault to ``source``.

        The first fault from a source is logged at WARNING with the exception,
        because it is the one that explains the rest. Subsequent ones are
        counted silently until the interval, so a controller that is faulting
        on every frame costs a bounded number of log lines rather than one per
        frame at 120 Hz.

        Args:
            source: Short name of what failed -- "hmd", "left_controller",
                "eye", "frame". Used as the tally key, so it must be stable.
            exc: The exception that was caught.
        """
        self.counts[source] += 1
        count = self.counts[source]
        if count == 1:
            logger.warning(
                f"{self.backend_name}: {source} tracking fault (first this session): "
                f"{type(exc).__name__}: {exc}"
            )
        elif count % REPEAT_LOG_INTERVAL == 0:
            logger.warning(
                f"{self.backend_name}: {source} has now failed to track on {count} frames."
            )

    @property
    def total(self) -> int:
        """Faults across every source."""
        return sum(self.counts.values())

    def summarise(self, frames_polled: int | None = None) -> None:
        """Log the session's totals. Called from a backend's ``shutdown``.

        Silent when nothing failed -- which is the point of it being here: a
        clean session says nothing, so a session that says something is one
        whose data needs looking at before it is used.

        Args:
            frames_polled: Total frames the backend was asked for, when known.
                Turns a raw count into a proportion, which is what decides
                whether a recording is usable.
        """
        if not self.counts:
            return

        parts = []
        for source, count in sorted(self.counts.items(), key=lambda kv: -kv[1]):
            if frames_polled:
                parts.append(f"{source}={count} ({count / frames_polled:.1%} of frames)")
            else:
                parts.append(f"{source}={count}")

        logger.warning(
            f"{self.backend_name}: tracking faults this session -- {', '.join(parts)}. "
            f"Frames from a faulting source carry create_empty() zeros with their "
            f"*_tracking_valid flag at 0.0, which is indistinguishable in the data "
            f"from hardware that was switched off. Check these counts before "
            f"treating the session as complete."
        )
