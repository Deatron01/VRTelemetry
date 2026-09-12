# src/core/exceptions.py
"""The failure vocabulary (VRT-13).

Before this ticket the codebase had four exception classes and sixty-two
``except Exception`` handlers. The ratio is the finding: almost nothing was
*raised* deliberately, so almost nothing could be *caught* deliberately either,
and every handler had to be written as "catch everything and hope".

That is not a style problem. A blanket handler cannot tell these apart:

* the headset is not plugged in -- expected, the workstation must still boot;
* the hub is unreachable -- expected, work queues locally;
* a typo passed a ``str`` where an ``int`` was wanted -- a bug, and swallowing
  it turns a five-minute stack trace into a fortnight of "the data looks odd".

VRT-22 is what that costs. A swallowed ``sqlite3.OperationalError`` around a
schema change could not be distinguished from a no-op, so every session's
metadata was discarded for days with nothing anywhere reporting a problem. The
long docstring in :mod:`src.infrastructure.persistence.migrations` sets out the
standard this module exists to serve.

The rule this hierarchy encodes
-------------------------------

**A boot step or a status probe may swallow anything. A write path must not.**

A researcher opening the app on a laptop away from the lab has no hub, no
headset and no licence server, and the app must still come up and show local
data. So the lifespan's boot steps, the hardware probes and the
``/api/sync/status`` counters are allowed to catch broadly -- they carry a
``# noqa: BLE001`` naming the reason, because the tolerance is a decision, not
an oversight.

Anything that records, persists or uploads is the opposite. It catches the
failures it can name and lets the rest travel, because a frame that was not
written is not the same as a frame that was.

Every class here is raised somewhere. The tree is deliberately shallow: it
exists so callers can say ``except AcquisitionError`` or ``except StorageError``
and mean something, not to mirror an org chart.
"""

from __future__ import annotations


class VRTelemetryError(Exception):
    """Base exception class for all custom VRTelemetry framework errors.

    Catching this means "a failure this application anticipated". Catching
    ``Exception`` means "a failure this application anticipated, plus every bug
    in it". The two are only the same until the first bug.
    """


class GDPRConsentError(VRTelemetryError):
    """
    Raised when biometric tracking initialization is attempted without explicit
    user consent, or if consent is programmatically revoked during a live session.
    Enforces compliance with biometric data collection regulations.
    """


class AcquisitionError(VRTelemetryError):
    """A fault between the VR runtime and a recorded frame.

    The category the audit called out: sixty-two blanket handlers concentrated
    in acquisition, which made "the subject's controller left the tracking
    volume" and "the runtime handle is stale" indistinguishable in the dataset.
    """


class HardwareBindingError(AcquisitionError):
    """
    Raised when the framework fails to attach to the OpenXR runtime or when
    critical hardware extensions (like headless mode) are completely unavailable.
    """


class BackendUnavailableError(HardwareBindingError):
    """Raised when the selected backend cannot bind to a runtime at all.

    Distinct from :class:`HardwareBindingError` in what the caller does with it:
    a binding error is a fault, this is an environment. A workstation with no
    headset attached raises this, and the API turns it into a stated reason on
    the session rather than a recording that starts, records nothing and stops.
    """


class SynchronizationError(AcquisitionError):
    """
    Raised when the producer-consumer ring buffer experiences catastrophic desynchronization
    or queue exhaustion that cannot be mitigated by standard frame drops.
    """


class AVCaptureUnavailableError(AcquisitionError):
    """An :class:`~src.core.interfaces.IAVCaptureBackend` cannot capture right now.

    Same relationship to A/V capture that :class:`BackendUnavailableError` has
    to VR backends: a workstation with no compositor mirror window found, no
    microphone bound, or a capture subprocess (ffmpeg) that failed to launch is
    an environment, not a defect. The caller's job is to say so on the session
    rather than fail the whole recording -- telemetry can proceed without A/V
    capture; it must never be the other way around.
    """


class StorageError(VRTelemetryError):
    """A fault in the local persistence path -- Parquet, SQLite or the filesystem."""


class StorageWriteError(StorageError):
    """Raised when telemetry cannot be written to disk.

    Never swallowed. A recording whose sink is broken is a recording that is
    not happening, and the engine stops rather than counting frames it did not
    persist -- which is the state ``AsyncParquetWriter.write_failed`` exists to
    make visible for the failures that occur mid-session, after ``start()``
    already succeeded.
    """
