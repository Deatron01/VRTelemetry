"""Tenant-isolation tests for the central server's write routes (VRT-4).

Before this fix, every data-intake route authorised the caller's
``activation_id`` and then passed the caller's *own* ``license_id`` straight
through to ``CentralDataManager``. Any holder of a valid activation could file
sessions, session logs, patient records and presence rows under another
organisation's licence.

These tests set up two tenants and assert the property that matters: a write
authenticated as tenant A can never land in tenant B, whatever the request body
says.

The module imports ``src.central_server.server``, which opens its databases at
import time (a known defect, fixed in VRT-12). Until then the fixture below
chdir's into a temporary directory *before* the import so no test ever touches
a real ``LicenseServer/`` or ``CentralServer/`` directory.
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


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Import the central server against a throwaway data root.

    Yields the freshly imported module so each test gets its own databases.
    ``chdir`` is required rather than merely preferred: the module resolves
    ``LicenseServer/licenses.db`` and ``CentralServer/central_data.db``
    relative to the process working directory (VRT-6 replaces this with typed
    settings).
    """
    monkeypatch.chdir(tmp_path)

    # Take a snapshot of any already-imported `src.*` modules and put it back on
    # teardown. Simply deleting them would leave a later test module to re-import
    # the package in a different order and trip the pre-existing circular import
    # between src.backends.__init__, src.backends.discovery and
    # src.backends.openxr_headless -- a real defect (VRT-12 removes the
    # import-time coupling that causes it), but not one this fixture should
    # provoke in unrelated tests.
    def _src_modules() -> dict[str, Any]:
        return {
            name: mod
            for name, mod in sys.modules.items()
            if name == "src" or name.startswith("src.")
        }

    saved = _src_modules()
    for name in saved:
        del sys.modules[name]

    try:
        yield importlib.import_module("src.central_server.server")
    finally:
        for name in list(_src_modules()):
            del sys.modules[name]
        sys.modules.update(saved)


@pytest.fixture
def two_tenants(server: Any) -> dict[str, dict[str, str]]:
    """Create two licensed organisations, each with one activated machine.

    Returns:
        Mapping of tenant name to its ``license_id`` and ``activation_id``.
    """
    tenants: dict[str, dict[str, str]] = {}
    for name in ("alpha", "beta"):
        created = server.license_mgr.create_license(
            email=f"{name}@example.test",
            org_name=f"{name.title()} Lab",
            plan="standard",
            max_seats=2,
            expires_in_days=365,
        )
        activated = server.license_mgr.activate(
            license_key=created["license_key"],
            hardware_fingerprint=f"fp-{name}",
            machine_label=f"{name}-workstation",
            os_platform="Windows",
            app_version="1.0.0",
            ip_address="127.0.0.1",
        )
        assert activated["ok"], activated
        tenants[name] = {
            "license_id": activated.get("license_id") or created["license_id"],
            "activation_id": activated["activation_id"],
        }

    assert tenants["alpha"]["license_id"] != tenants["beta"]["license_id"]
    return tenants


@pytest.fixture
def client(server: Any) -> Iterator[TestClient]:
    with TestClient(server.app) as test_client:
        yield test_client


# --------------------------------------------------------------------------- #
# The vulnerability: writing into someone else's tenant
# --------------------------------------------------------------------------- #


def test_session_upload_cannot_be_filed_under_another_tenant(
    client: TestClient, two_tenants: dict[str, dict[str, str]]
) -> None:
    """Alpha's activation claiming Beta's licence must be refused, not honoured."""
    response = client.post(
        "/data/upload-session",
        data={
            "activation_id": two_tenants["alpha"]["activation_id"],
            "license_id": two_tenants["beta"]["license_id"],  # the attack
            "session_id": "20260527_133428",
            "metadata_json": '{"total_frames": 1}',
        },
        files={"file": ("s.parquet", b"PAR1notreallyparquet", "application/octet-stream")},
    )

    assert response.status_code == 403
    assert "does not match" in response.json()["detail"]


def test_session_log_upload_cannot_be_filed_under_another_tenant(
    client: TestClient, two_tenants: dict[str, dict[str, str]]
) -> None:
    response = client.post(
        "/data/upload-session-log",
        data={
            "activation_id": two_tenants["alpha"]["activation_id"],
            "license_id": two_tenants["beta"]["license_id"],
            "session_id": "20260527_133428",
        },
        files={"file": ("s.log", b"log line", "text/plain")},
    )

    assert response.status_code == 403


def test_metadata_update_cannot_be_filed_under_another_tenant(
    client: TestClient, two_tenants: dict[str, dict[str, str]]
) -> None:
    response = client.post(
        "/data/update-session-metadata",
        data={
            "activation_id": two_tenants["alpha"]["activation_id"],
            "license_id": two_tenants["beta"]["license_id"],
            "session_id": "20260527_133428",
            "metadata_json": "{}",
        },
    )

    assert response.status_code == 403


def test_patient_upload_cannot_be_filed_under_another_tenant(
    client: TestClient, two_tenants: dict[str, dict[str, str]]
) -> None:
    response = client.post(
        "/data/upload-patient",
        json={
            "activation_id": two_tenants["alpha"]["activation_id"],
            "license_id": two_tenants["beta"]["license_id"],
            "patient": {"patient_id": "pat-1", "display_name": "Test Subject"},
        },
    )

    assert response.status_code == 403


def test_client_heartbeat_cannot_appear_under_another_tenant(
    client: TestClient, two_tenants: dict[str, dict[str, str]]
) -> None:
    """A presence row is a tenant write too -- it drives the Active Clients view."""
    response = client.post(
        "/client/heartbeat",
        data={
            "activation_id": two_tenants["alpha"]["activation_id"],
            "license_id": two_tenants["beta"]["license_id"],
            "status": "recording",
        },
    )

    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# The legitimate paths still work
# --------------------------------------------------------------------------- #


def test_matching_license_id_is_accepted(
    client: TestClient, two_tenants: dict[str, dict[str, str]]
) -> None:
    """A current client sending its own correct licence is unaffected."""
    response = client.post(
        "/client/heartbeat",
        data={
            "activation_id": two_tenants["alpha"]["activation_id"],
            "license_id": two_tenants["alpha"]["license_id"],
            "status": "idle",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_omitted_license_id_is_derived_server_side(
    client: TestClient, server: Any, two_tenants: dict[str, dict[str, str]]
) -> None:
    """A future client that stops sending the field is filed correctly anyway."""
    response = client.post(
        "/client/heartbeat",
        data={"activation_id": two_tenants["alpha"]["activation_id"], "status": "idle"},
    )
    assert response.status_code == 200

    clients = server.data_mgr.list_client_heartbeats()
    row = next(c for c in clients if c["activation_id"] == two_tenants["alpha"]["activation_id"])
    assert row["license_id"] == two_tenants["alpha"]["license_id"]


def test_unknown_activation_is_still_rejected(client: TestClient) -> None:
    """The pre-existing activation check must not have been weakened."""
    response = client.post(
        "/client/heartbeat",
        data={"activation_id": "does-not-exist", "status": "idle"},
    )

    assert response.status_code == 403
    assert "Unauthorized activation" in response.json()["detail"]


def test_rejection_logs_identifiers_but_not_payload(
    client: TestClient,
    two_tenants: dict[str, dict[str, str]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The audit line must name the attempt without echoing subject data (VRT-3)."""
    with caplog.at_level("ERROR"):
        client.post(
            "/data/upload-patient",
            json={
                "activation_id": two_tenants["alpha"]["activation_id"],
                "license_id": two_tenants["beta"]["license_id"],
                "patient": {"patient_id": "pat-1", "display_name": "Test Subject"},
            },
        )

    text = caplog.text
    assert "Cross-tenant write rejected" in text
    assert two_tenants["alpha"]["activation_id"] in text
    assert "Test Subject" not in text
