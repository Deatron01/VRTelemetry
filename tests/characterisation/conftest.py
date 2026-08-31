"""Fixtures for the workstation API characterisation suite (VRT-9).

These tests exist to hold the current behaviour of every route in
``src/main.py`` still while VRT-10 through VRT-14 move nearly every line of it.
They describe what the API does **today**, bugs included. Where a route is
wrong, the test says so and names the ticket that will change it; nothing here
is an endorsement.

Two constraints shape every fixture below.

**Importing ``src.main`` performs I/O.** It opens three SQLite databases,
constructs an HTTP uploader and reads the licence cache, all at module scope.
There is no seam to inject a fake, which is precisely why the API has had zero
test coverage. Rather than bolt a temporary seam onto production code, the
``workstation`` fixture chdir's into a temp directory and imports the module
fresh, so every database and output root is created inside ``tmp_path``. It is
not elegant; it is honest about what the module currently is, and it disappears
when VRT-12 introduces a composition root.

**The central server is not running.** ``TestClient`` is deliberately used
*without* its context manager, so the ``@app.on_event("startup")`` handlers
never fire -- they kick off a licence repair, a backfill sweep and two
background threads that would each try to reach ``127.0.0.1:9000``. On top of
that, ``requests`` is stubbed to raise ``RequestException`` for every call.
"Central server unreachable" is a documented, supported state for this
application, so it is the right default for a test: any route that only passes
with a live server was never offline-safe to begin with.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


class _UnreachableServer:
    """Stand-in for ``requests`` that fails every call the way an offline LAN does.

    Only the four verbs ``src.main`` actually uses are provided. The
    ``RequestException`` attribute is re-exported so the module's own
    ``except http_requests.RequestException`` clauses still match.
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


def _src_modules() -> dict[str, Any]:
    return {
        name: mod for name, mod in sys.modules.items() if name == "src" or name.startswith("src.")
    }


@pytest.fixture
def workstation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Import ``src.main`` against a throwaway data root, with no network.

    Yields the module itself, so tests can reach the module-level singletons
    (``_patients``, ``_db_manager_for_sync``, ``_local_cache``) to seed state
    directly instead of going through routes that are themselves under test.
    """
    monkeypatch.chdir(tmp_path)

    saved = _src_modules()
    for name in saved:
        del sys.modules[name]

    try:
        module = importlib.import_module("src.main")

        # Replace the module's `requests` alias, not the real library: other
        # modules imported into this same process must keep working normally.
        import requests as real_requests

        monkeypatch.setattr(module, "http_requests", _UnreachableServer(real_requests))

        # PatientSyncClient holds its own reference to requests, reached through
        # the uploader singletons rather than through src.main's alias.
        monkeypatch.setattr(
            module._patient_uploader,
            "sync_patient",
            lambda *_a, **_k: {"ok": False, "reason": "stubbed_offline"},
        )
        monkeypatch.setattr(
            module._session_uploader,
            "update_remote_metadata",
            lambda *_a, **_k: {"ok": False, "reason": "stubbed_offline"},
        )
        yield module
    finally:
        for name in list(_src_modules()):
            del sys.modules[name]
        sys.modules.update(saved)


@pytest.fixture
def client(workstation: Any) -> TestClient:
    """A TestClient with lifespan events deliberately NOT run.

    Using the context manager here would fire the startup handler, which
    launches the background sync scheduler and heartbeat threads and performs a
    licence-repair round trip. None of that is under test, all of it is slow,
    and the threads outlive the test.
    """
    return TestClient(workstation.app)


@pytest.fixture
def patient(workstation: Any) -> dict[str, Any]:
    """A consented patient, created directly through PatientManager."""
    return workstation._patients.create_patient(
        display_name="Test Subject",
        gdpr_consent_given=True,
        biological_sex="female",
        height_cm=170.0,
        weight_kg=65.0,
        dominant_hand="right",
        vr_experience_level="intermediate",
    )


@pytest.fixture
def session_row(workstation: Any, patient: dict[str, Any]) -> str:
    """A recorded session in vr_metadata.db. Returns its session_id.

    Written through DatabaseManager.persist_experiment rather than raw SQL so
    the fixture keeps working when VRT-11 replaces the storage layer.
    """
    session_id = "20260527_133428"
    workstation._db_manager_for_sync.persist_experiment(
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
def parquet_for_session(tmp_path: Path, session_row: str) -> Path:
    """A real Parquet file where get_session_telemetry expects to find one."""
    pytest.importorskip("pandas")
    import pandas as pd

    sessions_dir = tmp_path / "Sessions"
    sessions_dir.mkdir(exist_ok=True)
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
