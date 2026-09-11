"""Fixtures for the workstation API characterisation suite (VRT-9, rebuilt in VRT-12).

These tests exist to hold the behaviour of every route still while VRT-10
through VRT-14 move nearly every line beneath them. They describe what the API
does **today**, bugs included. Where a route is wrong, the test says so and
names the ticket that will change it; nothing here is an endorsement.

What changed in VRT-12
----------------------

The original version of this file was a confession. It read, in part:

    Importing ``src.main`` performs I/O. It opens three SQLite databases,
    constructs an HTTP uploader and reads the licence cache, all at module
    scope. There is no seam to inject a fake [...] the ``workstation`` fixture
    chdir's into a temp directory and imports the module fresh [...] It is not
    elegant; it is honest about what the module currently is, and it
    disappears when VRT-12 introduces a composition root.

This is that disappearance. There is no ``chdir``, no deleting entries from
``sys.modules``, no re-import, and no ``monkeypatch.setattr`` on a module
namespace. A test builds a :class:`~src.interfaces.api.container.Container`
against ``tmp_path``, replaces the collaborators it wants faked, and passes it
to :func:`~src.interfaces.api.app.create_app`.

The difference is not cosmetic. The old approach was capable of passing while
proving nothing: after VRT-10 split the routers out, the fixture went on
patching ``src.main.http_requests``, which no longer reached them -- every
"central server unreachable" test still passed, because CI has no central
server either. Injection cannot fail that way. There is no name to get wrong;
if the fake is not in the container, the container has the real thing and the
test talks to the network, loudly.

**The central server is not running.** ``TestClient`` is still used *without*
its context manager, so the lifespan never runs -- it kicks off a licence
repair, a backfill sweep and two background threads. On top of that, the
container's HTTP client is a stub that raises for every call. "Central server
unreachable" is a documented, supported state for this application, so it is
the right default for a test: any route that only passes against a live server
was never offline-safe to begin with.

What changed in VRT-14
----------------------

This file used to build a real container and then replace two bound methods on
``patient_uploader`` and ``session_uploader``, because those two clients held
their own ``requests`` reference and the container's ``http`` field did not
reach them. That is gone: the stub is passed to ``build_container`` and is the
only HTTP client anywhere in the container, so the offline guarantee no longer
depends on remembering which methods happen to make calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import PathSettings, Settings
from src.interfaces.api.app import create_app
from src.interfaces.api.container import Container, build_container


class _UnreachableServer:
    """Stand-in for ``requests`` that fails every call the way an offline LAN does.

    Only the four verbs the routers actually use are provided. The
    ``RequestException`` attribute is re-exported so each router's own
    ``except http.RequestException`` clause still matches.

    Every call is recorded. ``test_the_offline_stub_is_actually_in_force``
    asserts against that list, because a stub nothing reaches is worse than no
    stub at all: it makes a suite that quietly hits the network look green.
    """

    def __init__(self, real_requests: Any) -> None:
        self.RequestException = real_requests.RequestException
        self.calls: list[tuple[str, str]] = []

    def _fail(self, method: str, url: str) -> None:
        self.calls.append((method, url))
        raise self.RequestException(f"stubbed: central server unreachable ({method} {url})")

    def get(self, url: str, *_: Any, **__: Any) -> Any:
        self._fail("GET", url)

    def post(self, url: str, *_: Any, **__: Any) -> Any:
        self._fail("POST", url)

    def put(self, url: str, *_: Any, **__: Any) -> Any:
        self._fail("PUT", url)

    def delete(self, url: str, *_: Any, **__: Any) -> Any:
        self._fail("DELETE", url)


@pytest.fixture
def workstation(tmp_path: Path) -> Iterator[Container]:
    """A container built against a throwaway data root, with no network.

    Yields the container, so tests can reach a collaborator directly
    (``workstation.patients``, ``workstation.db_manager``) to seed state
    instead of going through routes that are themselves under test.

    The offline stub is reachable as ``workstation.http`` for the tests that
    assert on outbound calls.
    """
    import requests as real_requests

    settings = Settings(paths=PathSettings(data_root=tmp_path))
    stub = _UnreachableServer(real_requests)
    yield build_container(settings, http=stub)


@pytest.fixture
def app(workstation: Container) -> FastAPI:
    """An application built from the test's own container.

    Separate from ``client`` because the contract tests assert on the OpenAPI
    document rather than on responses, and building a TestClient to reach
    ``client.app`` would be indirection for its own sake.
    """
    return create_app(workstation)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """A TestClient over an application built from the test's own container.

    Deliberately *not* used as a context manager: entering it runs the lifespan,
    which performs a licence-repair round trip, a backfill sweep, and starts two
    background threads that would outlive the test. None of that is under test
    here; the lifespan has its own test in tests/integration/.
    """
    return TestClient(app)


@pytest.fixture
def patient(workstation: Container, consent_payload) -> dict[str, Any]:
    """A consented patient: a PatientManager row *and* a recorded consent.

    Since GDPR-09 the flag on the row is only a summary; a recording is
    authorised by the consent register. A fixture that set only the flag would
    describe a patient the application can no longer produce.
    """
    from src.interfaces.api.schemas.patients import ConsentSubmissionModel

    created = workstation.patients.create_patient(
        display_name="Test Subject",
        gdpr_consent_given=True,
        biological_sex="female",
        height_cm=170.0,
        weight_kg=65.0,
        dominant_hand="right",
        vr_experience_level="intermediate",
    )
    submission = ConsentSubmissionModel(**consent_payload()).to_domain()
    consent = workstation.consents.give(created["patient_id"], submission)
    return {**created, "consent_id": consent["consent_id"]}


@pytest.fixture
def session_row(workstation: Container, patient: dict[str, Any]) -> str:
    """A recorded session in vr_metadata.db. Returns its session_id.

    Written through DatabaseManager.persist_experiment rather than raw SQL so
    the fixture keeps working when the storage layer moves again.
    """
    session_id = "20260527_133428"
    workstation.db_manager.persist_experiment(
        {
            "M-IV_Static_Metadata": {
                "session_id": session_id,
                "subject_id": "SUB_TEST_01",
                "patient_id": patient["patient_id"],
                "start_timestamp_utc": "2026-05-27T13:34:28+00:00",
                "hmd_model": "Meta Quest Pro",
            },
            "H-VII_Hardware_Capabilities": {
                "hmd_model": "Meta Quest Pro",
                "has_eye_tracking": True,
            },
            "C-V_Calibration": {"dominant_hand": "right"},
        }
    )
    return session_id


@pytest.fixture
def parquet_for_session(workstation: Container, session_row: str) -> Path:
    """A real Parquet file where get_session_telemetry expects to find one."""
    pytest.importorskip("pandas")
    import pandas as pd

    sessions_dir = workstation.settings.paths.sessions_dir
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"vr_telemetry_{session_row}.parquet"
    pd.DataFrame(
        {
            # Deliberately large absolute nanosecond timestamps: the route
            # subtracts the first frame's value, and that behaviour is one of
            # the things this suite pins down.
            "timestamp_ns": [1_700_000_000_000_000_000 + i * 8_333_333 for i in range(10)],
            "frame_index": list(range(10)),
            "hmd_pos_x": [0.1 * i for i in range(10)],
            "left_eye_rot_w": [1.0] * 10,
        }
    ).to_parquet(path)
    return path
