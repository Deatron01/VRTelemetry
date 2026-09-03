"""The application's startup and shutdown sequence (VRT-12).

Nothing covered this before. The characterisation suite deliberately builds its
``TestClient`` *without* the context manager precisely so the lifespan does not
run -- it starts two background threads and makes a licence-repair round trip,
none of which those tests want. That left the boot path, which every real
launch of the desktop app executes, untested.

It is worth testing for a specific reason. Boot is the sequence most likely to
run in the condition nobody develops in: a researcher's laptop, away from the
lab, with the hub unreachable. Every step is individually guarded so the app
still comes up and serves the local UI. A guard nothing exercises is a guess.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.config import PathSettings, Settings
from src.interfaces.api.app import create_app
from src.interfaces.api.container import Container, build_container


class _Unreachable:
    """An HTTP client that fails the way an offline LAN does."""

    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException
        self.calls: list[str] = []

    def _fail(self, url: str) -> Any:
        self.calls.append(url)
        raise self.RequestException("stubbed: central server unreachable")

    def get(self, url: str, *_: Any, **__: Any) -> Any:
        return self._fail(url)

    def post(self, url: str, *_: Any, **__: Any) -> Any:
        return self._fail(url)


@pytest.fixture
def offline_container(tmp_path: Path) -> Container:
    """A container against a temp data root whose hub cannot be reached."""
    settings = Settings(paths=PathSettings(data_root=tmp_path))
    return build_container(settings, http=_Unreachable())


@pytest.fixture
def running_app(offline_container: Container) -> Iterator[TestClient]:
    """A client whose lifespan has genuinely run, torn down afterwards.

    The threads this starts are daemons, but leaving them running would let one
    test's scheduler sweep another test's database. The context manager's exit
    is what stops them, and it is the thing under test as much as the entry is.
    """
    with TestClient(create_app(offline_container)) as client:
        yield client


def test_the_application_starts_with_no_central_server(running_app: TestClient) -> None:
    """The condition a laptop away from the lab is always in.

    If this raised, the desktop app would show a blank window rather than the
    local UI, and the researcher would have no way to tell whether their
    recordings were safe.
    """
    response = running_app.get("/api/sessions")

    assert response.status_code == 200


def test_startup_runs_the_licence_repair(offline_container: Container) -> None:
    """The repair actually fires, rather than being silently skipped.

    Asserted through the HTTP stub's call log, because a boot sequence wrapped
    in three ``try/except`` blocks looks identical from the outside whether it
    ran or quietly did nothing.

    The cache is seeded into the exact state the repair exists for: an
    activation with no ``license_id``. Every upload from a machine in that
    state 422s server-side, so this is the one boot step whose absence a
    researcher would eventually notice -- as uploads that never succeed and
    never say why.
    """
    offline_container.local_cache.save(
        activation_id="act-boot-test",
        license_key="KEY-0001",
        hardware_fingerprint="fp",
        license_id=None,
        machine_label="lab-workstation-3",
        server_expires_at=None,
    )

    with TestClient(create_app(offline_container)):
        pass

    attempted = offline_container.http.calls  # type: ignore[attr-defined]

    assert any("/license/heartbeat" in url for url in attempted), (
        f"the licence repair never reached the hub; calls were {attempted}"
    )


def test_the_background_loops_belong_to_the_application(
    running_app: TestClient, offline_container: Container
) -> None:
    """Started by *this* app's lifespan, from *this* app's container.

    The old ``@app.on_event`` handlers closed over module-level singletons, so
    the loops belonged to the process. Two applications in one process started
    and stopped the same scheduler, and the second app's shutdown stopped the
    first app's syncing.
    """
    assert offline_container.sync_scheduler.is_running
    assert offline_container.heartbeat_sender.is_running

    body = running_app.get("/api/sync/status").json()

    assert body["background_sync_running"] is True
    assert body["heartbeat_running"] is True


def test_shutdown_stops_what_startup_started(offline_container: Container) -> None:
    """Leaving the loops running is how a test suite poisons its neighbours."""
    with TestClient(create_app(offline_container)):
        assert offline_container.sync_scheduler.is_running

    offline_container.sync_scheduler._thread.join(timeout=5)
    offline_container.heartbeat_sender._thread.join(timeout=5)

    assert not offline_container.sync_scheduler.is_running
    assert not offline_container.heartbeat_sender.is_running


def test_a_failing_boot_step_does_not_prevent_the_app_from_serving(
    offline_container: Container,
) -> None:
    """The whole reason each step is individually guarded.

    A corrupt licence cache, an unreadable Sessions folder or a hub returning
    nonsense must not cost the researcher access to their local data. This
    makes the first boot step raise something no ``except RequestException``
    would catch and asserts the app still comes up.
    """
    import src.interfaces.api.routers.licence as licence_module

    def _explode(_container: Container) -> None:
        raise MemoryError("simulated: the boot step failed in an unforeseen way")

    original = licence_module.repair_missing_license_id
    licence_module.repair_missing_license_id = _explode  # type: ignore[assignment]
    try:
        with TestClient(create_app(offline_container)) as client:
            assert client.get("/api/sessions").status_code == 200
            assert offline_container.sync_scheduler.is_running
    finally:
        licence_module.repair_missing_license_id = original  # type: ignore[assignment]
