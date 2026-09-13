# src/application/ports.py
"""What the application needs, said without naming who provides it (VRT-14).

A port is a ``Protocol``, not a base class, and that choice is the point:
``requests`` is a module, ``TestClient`` is not ours, and a fake written in a
test file is none of the above. Structural typing lets all three satisfy the
same contract without any of them inheriting from anything, which is what makes
"substitute a fake" a one-line construction rather than a class hierarchy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HttpClient(Protocol):
    """The outbound HTTP surface this application actually uses.

    Four verbs and one exception type -- deliberately smaller than
    ``requests``. A port is a statement about the *caller's* needs, so it lists
    what is called rather than what the library offers; anything not here is
    something no caller may start using without widening the contract on
    purpose.

    ``RequestException`` is part of the contract because every caller catches
    it. A fake that provides the methods but not the exception type produces a
    test suite where the offline path is never exercised -- which is precisely
    the failure this project has already had once (see the note in
    tests/characterisation/conftest.py).

    ``runtime_checkable`` so a test can assert a stub satisfies the shape
    before it is wired in. That check is shallow -- ``isinstance`` against a
    Protocol verifies the attributes exist, not their signatures -- so it is a
    smoke test, not a substitute for mypy.
    """

    #: The exception every method raises when the request could not be made.
    RequestException: type[Exception]

    def get(self, url: str, **kwargs: Any) -> Any: ...

    def post(self, url: str, **kwargs: Any) -> Any: ...

    def put(self, url: str, **kwargs: Any) -> Any: ...

    def delete(self, url: str, **kwargs: Any) -> Any: ...


# ─────────────────────────────────────────────────────────────────────────────
# Recording
# ─────────────────────────────────────────────────────────────────────────────
#
# A note on the port that is not here.
#
# The target architecture names three: FrameSource, FrameSink and
# SessionRepository. Only two of them are defined below, because
# ``src.core.interfaces.IVRBackend`` already *is* the frame source: an abstract
# class in the domain layer, with no I/O, describing exactly
# "initialize / poll_frame / shutdown". Restating it here as a Protocol would
# give one concept two names in two layers, and the first person to add a method
# would add it to one of them. It is referenced from here instead.
#
# ``SessionRepository`` likewise exists, in
# ``src.infrastructure.persistence``, but it is a concrete SQLite class rather
# than a port -- and the engine does not use it. What the engine needs is the
# one method below.


@runtime_checkable
class FrameSink(Protocol):
    """Where completed frames go.

    ``AsyncParquetWriter`` in production; a list in a test.

    ``write_failed`` is part of the contract rather than an implementation
    detail because the acquisition loop reads it every frame and stops
    collecting when it is true. A sink that cannot report having failed lets the
    engine count frames it did not persist -- which is the state
    ``TelemetryEngine._teardown`` exists to warn about.

    Declared as a read-only property, not a plain attribute: every caller in
    this codebase only ever reads ``sink.write_failed`` (the engine checks it,
    never sets it -- a sink decides its own failure internally). A plain
    ``write_failed: bool`` annotation would require every implementation to
    expose a *settable* attribute for structural compatibility, which is
    exactly what ``src.storage.tee_sink.TeeFrameSink`` deliberately does not
    do: it proxies reads to ``primary`` and has no setter, on purpose, so
    nothing can ever flip it independently of the sink that actually decides
    it.
    """

    #: True once the sink has given up. Never resets within a session.
    @property
    def write_failed(self) -> bool: ...

    def start(self) -> None: ...

    #: ``tuple[Any, ...]`` rather than ``tuple[float, ...]``: the first two
    #: fields of a frame are integers (frame index and a nanosecond
    #: timestamp) and the rest are floats, so a homogeneous annotation would
    #: be a more precise-looking lie than an honest one.
    def push(self, frame_tuple: tuple[Any, ...]) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class HardwareMetricsSource(Protocol):
    """Low-frequency host metrics folded into every frame.

    Attributes rather than methods because the synchroniser reads them on the
    acquisition thread at up to 120 Hz: whatever provides them must have
    already sampled them, not sample them on read.
    """

    cpu_usage: float
    voice_db: float
    gpu_usage: float

    def start(self) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class SessionMetadataSink(Protocol):
    """Where a session's static metadata is recorded.

    One method, deliberately. ``DatabaseManager`` is retained in the API's
    container solely because the engine calls this on it, and a port the width
    of the actual need is what lets that dependency be dropped.
    """

    def persist_experiment(self, metadata: dict[str, Any]) -> bool:
        """Persist the session's subject/hardware/system metadata.

        Returns:
            Whether the row was written. A false return is a reportable failure,
            not an exception: the recording continues without its metadata
            rather than being abandoned, and says so loudly. See VRT-22 for what
            it costs when that return value is discarded.
        """
        ...


@runtime_checkable
class SessionUploadPort(Protocol):
    """Getting a finished session to the hub, or queueing it until possible.

    Every method returns a result dict rather than raising, because "the hub is
    unreachable" is a supported state for this application rather than an error:
    the work is queued locally and swept later.
    """

    def upload(
        self, parquet_path: Path, session_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any]: ...

    def upload_log(self, log_path: Path, session_id: str) -> dict[str, Any]: ...

    def retry_pending(self) -> dict[str, Any]: ...


class ConsentStore(Protocol):
    """Append-only storage for consent evidence (GDPR-09).

    Implemented by
    :class:`src.infrastructure.persistence.consent_repository.ConsentRepository`,
    which also makes the rows immutable at the database level. There is no
    update and no delete here on purpose: a consent store that can rewrite its
    own history cannot demonstrate anything (Art. 7(1) GDPR).
    """

    def insert_consent(self, record: dict[str, Any]) -> None: ...

    def insert_event(
        self,
        *,
        patient_id: str,
        event_type: str,
        occurred_at_utc: str,
        consent_id: str | None = None,
        scope: str | None = None,
        detail: str | None = None,
    ) -> None: ...

    def get(self, consent_id: str) -> dict[str, Any] | None: ...

    def list_for_patient(self, patient_id: str) -> list[dict[str, Any]]: ...

    def find_by_withdrawal_code_hash(self, code_sha256: str) -> dict[str, Any] | None: ...

    def events_for_patient(self, patient_id: str) -> list[dict[str, Any]]: ...

    def is_ended(self, consent_id: str) -> bool: ...

    def is_research_withdrawn(self, consent_id: str) -> bool: ...

    def is_av_recording_withdrawn(self, consent_id: str) -> bool: ...
