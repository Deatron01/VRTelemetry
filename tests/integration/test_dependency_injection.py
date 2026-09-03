"""Collaborators are injected, not patched (VRT-12).

The third acceptance criterion of the composition root, and the one that is
easiest to believe without checking.

Before this, a test that wanted a fake had exactly one move: reach into a
module's namespace with ``monkeypatch.setattr`` and hope every caller looked
the name up by the same path. That is not a seam, it is a coincidence, and in
VRT-10 the coincidence broke -- the fixture went on patching
``src.main.http_requests`` after the routers had moved to
``dependencies.http_requests``, and every "the central server is unreachable"
test kept passing, because CI has no central server either. Twelve tests
asserting nothing, all green.

These tests assert the two properties that make that class of failure
impossible: a substituted collaborator really is the one the route uses, and
substituting it in one application does not touch another.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.config import PathSettings, Settings
from src.interfaces.api import dependencies
from src.interfaces.api.app import create_app
from src.interfaces.api.container import Container, build_container


def _container(root: Path, http: Any = None) -> Container:
    return build_container(Settings(paths=PathSettings(data_root=root)), http=http)


def test_a_dependency_override_reaches_the_route(tmp_path: Path) -> None:
    """``app.dependency_overrides`` is the supported way to substitute a fake.

    Scoped to the application rather than to the process, so it cannot leak
    into another test the way a patched module attribute can.
    """

    class _OnePatient:
        def list_patients(self, **_: Any) -> list[dict[str, str]]:
            return [{"patient_id": "injected", "display_name": "Not From The Database"}]

    app = create_app(_container(tmp_path))
    app.dependency_overrides[dependencies.get_patients] = _OnePatient

    body = TestClient(app).get("/api/patients").json()

    assert body == [{"patient_id": "injected", "display_name": "Not From The Database"}]


def test_removing_an_override_restores_the_real_collaborator(tmp_path: Path) -> None:
    """The override is reversible, and reversing it brings back the real thing.

    A monkeypatched module attribute is reversible only by convention -- if the
    test forgets, or fails before its teardown, the next test inherits the fake.
    """
    container = _container(tmp_path)
    container.patients.create_patient(display_name="Genuinely Stored", gdpr_consent_given=True)
    app = create_app(container)
    app.dependency_overrides[dependencies.get_patients] = _Empty
    client = TestClient(app)
    assert client.get("/api/patients").json() == []

    app.dependency_overrides.clear()

    assert [p["display_name"] for p in client.get("/api/patients").json()] == ["Genuinely Stored"]


class _Empty:
    def list_patients(self, **_: Any) -> list[Any]:
        return []


def test_two_applications_do_not_share_collaborators(tmp_path: Path) -> None:
    """Writing through one application must be invisible to the other.

    This is what the module-level singletons made impossible, and it is why the
    characterisation suite used to delete ``src.*`` from ``sys.modules`` and
    re-import between tests. Databases in separate roots, registries in
    separate objects, no shared process state anywhere.
    """
    first = create_app(_container(tmp_path / "lab-a"))
    second = create_app(_container(tmp_path / "lab-b"))

    created = (
        TestClient(first)
        .post(
            "/api/patients",
            json={"display_name": "Only In Lab A", "gdpr_consent_given": True},
        )
        .json()
    )

    assert created["display_name"] == "Only In Lab A"
    assert TestClient(second).get("/api/patients").json() == []
    assert [p["display_name"] for p in TestClient(first).get("/api/patients").json()] == [
        "Only In Lab A"
    ]
    # Two roots, two databases. Before VRT-12 both applications would have been
    # reading the one opened when `dependencies` was first imported.
    assert (tmp_path / "lab-a" / "Sessions" / "patients.db").exists()
    assert (tmp_path / "lab-b" / "Sessions" / "patients.db").exists()


def test_an_override_on_one_application_does_not_affect_another(tmp_path: Path) -> None:
    """The property a patched module attribute cannot have."""
    first = create_app(_container(tmp_path / "a"))
    second = create_app(_container(tmp_path / "b"))
    first.dependency_overrides[dependencies.get_patients] = lambda: _OneFake()

    assert TestClient(first).get("/api/patients").json() == [{"patient_id": "fake"}]
    assert TestClient(second).get("/api/patients").json() == []


class _OneFake:
    def list_patients(self, **_: Any) -> list[dict[str, str]]:
        return [{"patient_id": "fake"}]


def test_the_http_client_is_a_container_attribute_not_a_module_import(
    tmp_path: Path,
) -> None:
    """Replacing it is one constructor argument, not a name in eight modules.

    The stub below is reached only if every outbound call in the routers goes
    through ``container.http``. If one of them still imported ``requests``
    directly, this test would make a real network call to a nonexistent host
    and the assertion on ``calls`` would fail.
    """

    class _Recording:
        def __init__(self) -> None:
            import requests

            self.RequestException = requests.RequestException
            self.calls: list[str] = []

        def post(self, url: str, *_: Any, **__: Any) -> Any:
            self.calls.append(url)
            raise self.RequestException("stubbed")

        def get(self, url: str, *_: Any, **__: Any) -> Any:
            self.calls.append(url)
            raise self.RequestException("stubbed")

    stub = _Recording()
    container = _container(tmp_path, http=stub)
    container.local_cache.set_config("central_server_url", "http://hub.invalid:9000")
    client = TestClient(create_app(container))

    client.post("/api/auth/login", json={"email": "a@b.test", "password": "hunter22"})
    client.post("/api/license/activate", json={"license_key": "K", "machine_label": "m"})
    client.get("/api/auth/session")

    assert stub.calls == [
        "http://hub.invalid:9000/auth/login",
        "http://hub.invalid:9000/license/activate",
    ], f"a router bypassed container.http and called the network directly: {stub.calls}"


def test_the_uploaders_go_through_the_same_client_as_the_routers(tmp_path: Path) -> None:
    """The half of the seam VRT-12 did not close (VRT-14).

    ``SessionUploader``, ``PatientSyncClient`` and ``HeartbeatSender`` used to
    import ``requests`` themselves, so an "offline" container reached the
    network through them while the routers were correctly stubbed. The
    characterisation suite worked around it by replacing two bound methods, with
    a comment naming this ticket.

    This asserts the workaround is no longer needed: creating a patient through
    the API reaches the hub through the *same* stub the routers use.
    """

    class _Recording:
        def __init__(self) -> None:
            import requests

            self.RequestException = requests.RequestException
            self.calls: list[str] = []

        def post(self, url: str, *_: Any, **__: Any) -> Any:
            self.calls.append(url)
            raise self.RequestException("stubbed")

        def get(self, url: str, *_: Any, **__: Any) -> Any:
            self.calls.append(url)
            raise self.RequestException("stubbed")

    stub = _Recording()
    container = _container(tmp_path, http=stub)
    container.local_cache.set_config("central_server_url", "http://hub.invalid:9000")
    # PatientSyncClient declines to call out at all without an active licence,
    # so the stub would record nothing and the test would pass vacuously.
    container.local_cache.save(
        activation_id="ACT-1",
        license_key="K",
        hardware_fingerprint="FP-1",
        license_id="LIC-1",
        machine_label="bench",
    )
    client = TestClient(create_app(container))

    client.post(
        "/api/patients",
        json={"display_name": "Subject A", "gdpr_consent_given": True},
    )

    assert "http://hub.invalid:9000/data/upload-patient" in stub.calls, (
        "PatientSyncClient bypassed container.http: it is holding its own "
        f"requests reference again. Calls seen: {stub.calls}"
    )


def test_a_container_whose_clients_disagree_about_the_network_is_refused(
    tmp_path: Path,
) -> None:
    """`dataclasses.replace(container, http=stub)` must not half-work.

    It is the obvious way to build an offline container and it used to repoint
    the routers only, leaving the three clients on the real library. A test
    written that way passes while reaching the network. The container refuses
    the state instead of documenting it.
    """
    import dataclasses

    container = _container(tmp_path)

    class _Other:
        RequestException = RuntimeError

        def get(self, url: str, *_: Any, **__: Any) -> Any: ...
        def post(self, url: str, *_: Any, **__: Any) -> Any: ...
        def put(self, url: str, *_: Any, **__: Any) -> Any: ...
        def delete(self, url: str, *_: Any, **__: Any) -> Any: ...

    with pytest.raises(ValueError) as caught:
        dataclasses.replace(container, http=_Other())

    message = str(caught.value)
    assert "session_uploader" in message
    assert "patient_uploader" in message
    assert "heartbeat_sender" in message
    assert "build_container" in message, "the error must say how to do it correctly"


def test_a_route_on_an_app_built_outside_create_app_fails_loudly(tmp_path: Path) -> None:
    """No container means a stated error, not an AttributeError from a handler.

    Someone will eventually assemble a FastAPI app by hand and mount these
    routers on it. When they do, the message should say what is missing.
    """
    from fastapi import FastAPI

    from src.interfaces.api.routers import patients

    bare = FastAPI()
    bare.include_router(patients.router)

    with pytest.raises(RuntimeError, match="create_app"):
        TestClient(bare, raise_server_exceptions=True).get("/api/patients")
