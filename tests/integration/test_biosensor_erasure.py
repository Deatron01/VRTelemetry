# tests/integration/test_biosensor_erasure.py
"""Erasure reaches the biosensor sidecar and its provenance rows (VRT-37).

The authoritative-store decision recorded in ``src.application.erasure`` and
``src.storage.biosensor_sidecar`` (host-changes doc §6): the sidecar Parquet
and ``biosensor_streams`` are the record erasure acts on. Two paths exercise
that decision -- a full participant erasure (which must not leave a device
identifier behind in ``biosensor_streams``, unlike the pre-existing
``av_recordings`` row, see the module docstring for why the two differ), and
the targeted :meth:`ErasureService.erase_biosensor_data`, the workstation
half of a future ``WithdrawalScope.BIOSENSOR_ONLY`` that is not yet wired to
a consent scope or an API route (that needs VRT-38's legal/consent-catalogue
work first).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.application.erasure import ErasureBlockedError
from src.config import PathSettings, Settings
from src.interfaces.api.app import create_app
from src.interfaces.api.container import Container, build_container

SESSION_ID = "20260918_120000"


class _Hub:
    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException

    def post(self, *_: Any, **__: Any) -> Any:
        raise self.RequestException("stubbed: not reached by this scope")

    get = put = delete = post


def _workstation(tmp_path: Path) -> Container:
    container = build_container(Settings(paths=PathSettings(data_root=tmp_path)), http=_Hub())
    container.local_cache.set_config("central_server_url", "https://hub.test:9000")
    container.local_cache.save(
        activation_id="ACT-1",
        license_key="K",
        hardware_fingerprint="FP-1",
        license_id="LIC-1",
        machine_label="bench",
    )
    return container


def _enrol_with_biosensor_data(container: Container, client: TestClient, consent_payload) -> dict:
    response = client.post(
        "/api/patients", json={"display_name": "Bence Kis", "consent": consent_payload()}
    )
    assert response.status_code == 200, response.text
    patient = response.json()

    container.db_manager.persist_experiment(
        {
            "M-IV_Static_Metadata": {
                "session_id": SESSION_ID,
                "patient_id": patient["patient_id"],
                "consent_id": patient["consent"]["consent_id"],
            }
        }
    )
    paths = container.settings.paths
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.parquet").write_bytes(b"raw")
    (paths.sessions_dir / f"vr_biosensors_{SESSION_ID}.parquet").write_bytes(b"sidecar")
    container.biosensor_streams.record_batch(
        session_id=SESSION_ID,
        device_id="polar-h10-a1b2",
        producer_id="biosensor-plugin-01",
        channels={"heart_rate_bpm"},
        accepted=42,
        dropped=0,
        received_at_utc="2026-09-18T12:00:00",
    )
    return patient


def test_full_erasure_removes_the_sidecar_file_and_its_provenance_row(
    tmp_path: Path, consent_payload: Any
) -> None:
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    patient = _enrol_with_biosensor_data(container, client, consent_payload)

    response = client.delete(f"/api/patients/{patient['patient_id']}")

    assert response.status_code == 200, response.text
    report = response.json()["erasure"]
    assert report["sessions"] == 1
    assert report["files_deleted"] == 2  # the telemetry parquet and the sidecar

    paths = container.settings.paths
    assert not (paths.sessions_dir / f"vr_biosensors_{SESSION_ID}.parquet").exists()
    assert container.biosensor_streams.list_for_session(SESSION_ID) == []


def test_erase_biosensor_data_leaves_the_telemetry_and_consent_untouched(
    tmp_path: Path, consent_payload: Any
) -> None:
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    patient = _enrol_with_biosensor_data(container, client, consent_payload)

    report = container.erasure.erase_biosensor_data(patient["patient_id"])

    assert report.session_ids == [SESSION_ID]
    assert report.files_deleted == [f"vr_biosensors_{SESSION_ID}.parquet"]

    paths = container.settings.paths
    assert not (paths.sessions_dir / f"vr_biosensors_{SESSION_ID}.parquet").exists()
    assert container.biosensor_streams.list_for_session(SESSION_ID) == []
    # The telemetry recording, the session row and the patient's consent are
    # untouched -- only the biosensor data was withdrawn.
    assert (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.parquet").exists()
    assert container.sessions.session_ids_for_patient(patient["patient_id"]) == [SESSION_ID]
    stored = container.patients.get_patient(patient["patient_id"])
    assert bool(stored["gdpr_consent_given"]) is True

    history = container.consents.history(patient["patient_id"])
    assert [e["event_type"] for e in history["events"]] == ["given", "erased"]


def test_erase_biosensor_data_is_a_no_op_file_wise_with_no_biosensor_data(
    tmp_path: Path, consent_payload: Any
) -> None:
    """A participant with no biosensor plugin ever connected: nothing to erase, no error."""
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    response = client.post(
        "/api/patients", json={"display_name": "No Sensor", "consent": consent_payload()}
    )
    patient_id = response.json()["patient_id"]
    container.db_manager.persist_experiment(
        {
            "M-IV_Static_Metadata": {
                "session_id": SESSION_ID,
                "patient_id": patient_id,
                "consent_id": response.json()["consent"]["consent_id"],
            }
        }
    )

    report = container.erasure.erase_biosensor_data(patient_id)

    assert report.session_ids == [SESSION_ID]
    assert report.files_deleted == []


def test_a_participant_being_recorded_cannot_withdraw_biosensor_data_mid_session(
    tmp_path: Path, consent_payload: Any
) -> None:
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    patient = _enrol_with_biosensor_data(container, client, consent_payload)
    container.erasure.is_recording_patient = lambda pid: pid == patient["patient_id"]

    with pytest.raises(ErasureBlockedError):
        container.erasure.erase_biosensor_data(patient["patient_id"])

    paths = container.settings.paths
    assert (paths.sessions_dir / f"vr_biosensors_{SESSION_ID}.parquet").exists()
