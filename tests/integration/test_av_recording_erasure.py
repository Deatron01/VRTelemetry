# tests/integration/test_av_recording_erasure.py
"""Withdrawing P-C7 alone (addendum Section 3.4), end to end on a workstation.

The regression this guards: SPEECH_RECORDING_ONLY used to fall into the same
branch as FUTURE_ONLY/ALL_DELETE and call ``patients.withdraw_consent()``,
which sets ``gdpr_consent_given = 0`` -- stopping *all* future recording for a
participant who only withdrew the A/V portion. It must instead behave like
PROVIDER_RESEARCH_ONLY for the patient row, while also erasing the A/V files
and the ``av_recordings`` row -- which PROVIDER_RESEARCH_ONLY does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.config import ConsentSettings, PathSettings, Settings
from src.interfaces.api.app import create_app
from src.interfaces.api.container import Container, build_container

SESSION_ID = "20260912_090000"


class _Hub:
    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException

    def post(self, *_: Any, **__: Any) -> Any:
        raise self.RequestException("stubbed: not reached by this scope")

    get = put = delete = post


def _workstation(tmp_path: Path) -> Container:
    settings = Settings(
        paths=PathSettings(data_root=tmp_path),
        consent=ConsentSettings(enable_av_recording=True),
    )
    container = build_container(settings, http=_Hub())
    container.local_cache.set_config("central_server_url", "https://hub.test:9000")
    container.local_cache.save(
        activation_id="ACT-1",
        license_key="K",
        hardware_fingerprint="FP-1",
        license_id="LIC-1",
        machine_label="bench",
    )
    return container


def _enrol_with_av_recording(container: Container, client: TestClient, consent_payload) -> dict:
    payload = consent_payload(ConsentSettings(enable_av_recording=True))
    response = client.post("/api/patients", json={"display_name": "Bence Kis", "consent": payload})
    assert response.status_code == 200, response.text
    patient = response.json()
    consent_id = patient["consent"]["consent_id"]

    container.db_manager.persist_experiment(
        {
            "M-IV_Static_Metadata": {
                "session_id": SESSION_ID,
                "patient_id": patient["patient_id"],
                "consent_id": consent_id,
            }
        }
    )
    paths = container.settings.paths
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.parquet").write_bytes(b"raw")
    (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.mp4").write_bytes(b"video")
    (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.transcript.json").write_text("{}")
    container.av_recordings.create(
        {
            "session_id": SESSION_ID,
            "patient_id": patient["patient_id"],
            "consent_id": consent_id,
            "capture_backend": "pc_compositor_mirror",
            "created_at_utc": "2026-09-12T09:00:00",
        }
    )
    return patient


def test_withdrawing_speech_recording_only_erases_only_the_av_files(
    tmp_path: Path, consent_payload
) -> None:
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    patient = _enrol_with_av_recording(container, client, consent_payload)

    response = client.post(
        f"/api/patients/{patient['patient_id']}/withdraw-consent",
        json={"scope": "SPEECH_RECORDING_ONLY"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["erasure"]["sessions"] == 1
    assert body["erasure"]["files_deleted"] == 2  # the .mp4 and the .transcript.json

    paths = container.settings.paths
    assert not (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.mp4").exists()
    assert not (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.transcript.json").exists()
    # The telemetry recording is untouched.
    assert (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.parquet").exists()
    assert container.av_recordings.get(SESSION_ID) is None


def test_withdrawing_speech_recording_only_does_not_block_future_telemetry(
    tmp_path: Path, consent_payload
) -> None:
    """The bug this test exists to catch: SPEECH_RECORDING_ONLY must not set
    gdpr_consent_given = 0, unlike FUTURE_ONLY and ALL_DELETE."""
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    patient = _enrol_with_av_recording(container, client, consent_payload)

    client.post(
        f"/api/patients/{patient['patient_id']}/withdraw-consent",
        json={"scope": "SPEECH_RECORDING_ONLY"},
    )

    stored = container.patients.get_patient(patient["patient_id"])
    assert bool(stored["gdpr_consent_given"]) is True

    # The consent still authorises a (telemetry-only) recording.
    record = container.consents.require_for_recording(patient["patient_id"], None)
    assert record["consent_id"] == patient["consent"]["consent_id"]
    assert container.consents.av_recording_permitted(record["consent_id"]) is False


def test_withdrawing_speech_recording_only_is_reported_in_consent_history(
    tmp_path: Path, consent_payload
) -> None:
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    patient = _enrol_with_av_recording(container, client, consent_payload)

    client.post(
        f"/api/patients/{patient['patient_id']}/withdraw-consent",
        json={"scope": "SPEECH_RECORDING_ONLY"},
    )

    history = container.consents.history(patient["patient_id"])
    # "erased" follows "av_recording_withdrawn": erase_av_recordings() itself
    # appends it (mirrors ALL_DELETE's own withdraw -> erase sequence, see
    # test_erasure.py::test_withdrawing_with_erasure_does_both).
    assert [e["event_type"] for e in history["events"]] == [
        "given",
        "av_recording_withdrawn",
        "erased",
    ]


def test_a_participant_being_recorded_cannot_withdraw_av_recording_mid_session(
    tmp_path: Path, consent_payload
) -> None:
    container = _workstation(tmp_path)
    client = TestClient(create_app(container))
    patient = _enrol_with_av_recording(container, client, consent_payload)
    container.erasure.is_recording_patient = lambda pid: pid == patient["patient_id"]

    response = client.post(
        f"/api/patients/{patient['patient_id']}/withdraw-consent",
        json={"scope": "SPEECH_RECORDING_ONLY"},
    )

    assert response.status_code == 409
    paths = container.settings.paths
    assert (paths.sessions_dir / f"vr_telemetry_{SESSION_ID}.mp4").exists()
