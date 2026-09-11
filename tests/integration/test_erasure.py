# tests/integration/test_erasure.py
"""The right to erasure, end to end on a workstation (GDPR-10).

The bug this replaces: ``DELETE /api/patients/{id}`` blanked the name on the
patient row and left every recording -- Parquet files, session rows, logs, the
upload queue and every copy on the hub -- linked to the same id. So each test
here checks a *place*, and asserts the participant is gone from it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.config import PathSettings, Settings
from src.interfaces.api.app import create_app
from src.interfaces.api.container import Container, build_container

SESSION_ID = "20260911_101500"


class _Hub:
    """An HTTP client standing in for the hub: records requests, answers as configured."""

    def __init__(self, *, reachable: bool = True) -> None:
        import requests

        self.RequestException = requests.RequestException
        self.reachable = reachable
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, *_: Any, **kwargs: Any) -> Any:
        self.posts.append((url, kwargs.get("json") or {}))
        if not self.reachable:
            raise self.RequestException("stubbed: hub unreachable")
        return _Ok()

    def get(self, *_: Any, **__: Any) -> Any:
        raise self.RequestException("stubbed")

    put = delete = get


class _Ok:
    status_code = 200
    text = "ok"

    def json(self) -> dict[str, Any]:
        return {"ok": True, "complete": True}


def _workstation(tmp_path: Path, hub: _Hub) -> Container:
    container = build_container(Settings(paths=PathSettings(data_root=tmp_path)), http=hub)
    container.local_cache.set_config("central_server_url", "https://hub.test:9000")
    container.local_cache.save(
        activation_id="ACT-1",
        license_key="K",
        hardware_fingerprint="FP-1",
        license_id="LIC-1",
        machine_label="bench",
    )
    return container


def _enrol_and_record(container: Container, client: TestClient, consent: dict) -> str:
    """A participant with one recorded session, a log, and a queued upload."""
    patient = client.post("/api/patients", json={"display_name": "Anna Kovács", "consent": consent})
    patient = patient.json()
    patient_id = patient["patient_id"]
    container.db_manager.persist_experiment(
        {
            "M-IV_Static_Metadata": {
                "session_id": SESSION_ID,
                "patient_id": patient_id,
                "consent_id": patient["consent"]["consent_id"],
            }
        }
    )
    paths = container.settings.paths
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    paths.session_logs_dir.mkdir(parents=True, exist_ok=True)
    (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.parquet").write_bytes(b"raw")
    (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}_ai_ready.parquet").write_bytes(b"derived")
    (paths.session_logs_dir / f"session_{SESSION_ID}.log").write_text("log")
    container.local_cache.queue_pending_upload(
        SESSION_ID, str(paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.parquet"), "{}"
    )
    return patient_id


def test_erasure_removes_the_participant_from_every_local_store(
    tmp_path: Path, consent_payload: Any
) -> None:
    hub = _Hub()
    container = _workstation(tmp_path, hub)
    client = TestClient(create_app(container))
    patient_id = _enrol_and_record(container, client, consent_payload())

    response = client.delete(f"/api/patients/{patient_id}")

    assert response.status_code == 200, response.text
    report = response.json()["erasure"]
    assert report["sessions"] == 1 and report["files_deleted"] == 3
    assert list(container.settings.paths.sessions_dir.glob("*.parquet")) == []
    assert list(container.settings.paths.session_logs_dir.glob("*.log")) == []
    assert container.sessions.session_ids_for_patient(patient_id) == []
    assert container.local_cache.list_pending_uploads() == []
    stored = container.patients.get_patient(patient_id)
    assert stored["is_anonymized"] and stored["display_name"] == "[ERASED]"


def test_erasure_asks_the_hub_to_delete_its_copies(tmp_path: Path, consent_payload: Any) -> None:
    hub = _Hub()
    container = _workstation(tmp_path, hub)
    client = TestClient(create_app(container))
    patient_id = _enrol_and_record(container, client, consent_payload())

    report = client.delete(f"/api/patients/{patient_id}").json()["erasure"]

    [body] = [b for u, b in hub.posts if u.endswith("/data/erase-patient")]
    assert body["patient_id"] == patient_id
    assert body["session_ids"] == [SESSION_ID]
    assert report["hub_confirmed"] is True
    assert container.local_cache.list_pending_erasures() == []


def test_an_unreachable_hub_leaves_the_erasure_queued_not_forgotten(
    tmp_path: Path, consent_payload: Any
) -> None:
    hub = _Hub(reachable=False)
    container = _workstation(tmp_path, hub)
    client = TestClient(create_app(container))
    patient_id = _enrol_and_record(container, client, consent_payload())

    report = client.delete(f"/api/patients/{patient_id}").json()["erasure"]

    assert report["hub_confirmed"] is False and report["hub_queued"] is True
    [pending] = container.local_cache.list_pending_erasures()
    assert pending["patient_id"] == patient_id
    assert json.loads(pending["session_ids_json"]) == [SESSION_ID]
    assert all(
        p["patient_id"] != patient_id for p in container.local_cache.list_pending_patient_syncs()
    )

    # Past the retry backoff: the sweep skips an item that failed seconds ago.
    with sqlite3.connect(container.settings.paths.license_cache_db) as conn:
        conn.execute("UPDATE pending_hub_erasures SET last_attempt_at = '2000-01-01 00:00:00'")
    hub.reachable = True
    container.patient_uploader.retry_pending()

    assert container.local_cache.list_pending_erasures() == []


def test_the_consent_evidence_survives_the_erasure(tmp_path: Path, consent_payload: Any) -> None:
    """It holds only the pseudonymous id, and shows the recordings were lawful."""
    container = _workstation(tmp_path, _Hub())
    client = TestClient(create_app(container))
    patient_id = _enrol_and_record(container, client, consent_payload())

    client.delete(f"/api/patients/{patient_id}")

    history = container.consents.history(patient_id)
    assert len(history["consents"]) == 1
    assert [e["event_type"] for e in history["events"]] == ["given", "erased"]


def test_withdrawing_with_erasure_does_both(tmp_path: Path, consent_payload: Any) -> None:
    container = _workstation(tmp_path, _Hub())
    client = TestClient(create_app(container))
    patient_id = _enrol_and_record(container, client, consent_payload())

    response = client.post(
        f"/api/patients/{patient_id}/withdraw-consent", json={"scope": "ALL_DELETE"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["erasure"]["files_deleted"] == 3
    events = [e["event_type"] for e in container.consents.history(patient_id)["events"]]
    assert events == ["given", "withdrawn", "erased"]


def test_hard_delete_can_no_longer_orphan_sessions(tmp_path: Path, consent_payload: Any) -> None:
    """GDPR-05: the session rows are gone before the patient row is."""
    container = _workstation(tmp_path, _Hub())
    client = TestClient(create_app(container))
    patient_id = _enrol_and_record(container, client, consent_payload())

    client.delete(f"/api/patients/{patient_id}", params={"hard_delete": True})

    assert container.patients.get_patient(patient_id) is None
    assert container.sessions.session_ids_for_patient(patient_id) == []


def test_a_participant_being_recorded_cannot_be_erased_mid_session(
    tmp_path: Path, consent_payload: Any
) -> None:
    container = _workstation(tmp_path, _Hub())
    client = TestClient(create_app(container))
    patient_id = _enrol_and_record(container, client, consent_payload())
    container.erasure.is_recording_patient = lambda pid: pid == patient_id

    response = client.delete(f"/api/patients/{patient_id}")

    assert response.status_code == 409
    assert (container.settings.paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.parquet").exists()
