"""Characterisation of the patient registry routes (VRT-9).

Covers 5 routes:

    GET    /api/patients
    POST   /api/patients
    PUT    /api/patients/{id}
    DELETE /api/patients/{id}
    POST   /api/patients/{id}/withdraw-consent

The GDPR consent lifecycle lives here, so these are the tests most worth having
before anything moves. Consent is not a field to be refactored casually: the
rules below are the difference between a lawful study and an unlawful one.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

NEW_PATIENT = {
    "display_name": "Subject A",
    "gdpr_consent_given": True,
    "biological_sex": "male",
    "height_cm": 182.0,
    "weight_kg": 78.0,
    "dominant_hand": "right",
    "vr_experience_level": "novice",
    "motion_sickness_susceptibility": "low",
}


def test_list_patients_starts_empty(client: TestClient) -> None:
    assert client.get("/api/patients").json() == []


def test_create_patient_returns_the_stored_record(client: TestClient) -> None:
    response = client.post("/api/patients", json=NEW_PATIENT)

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Subject A"
    assert body["gdpr_consent_given"]
    assert body["patient_id"]
    assert not body["is_anonymized"]


def test_create_patient_without_consent_is_refused(client: TestClient) -> None:
    """A patient record cannot exist without consent. This is the load-bearing rule."""
    response = client.post("/api/patients", json={**NEW_PATIENT, "gdpr_consent_given": False})

    assert response.status_code == 403


def test_create_patient_requires_a_display_name(client: TestClient) -> None:
    response = client.post("/api/patients", json={"gdpr_consent_given": True})

    assert response.status_code == 422


def test_health_profile_fields_round_trip(client: TestClient) -> None:
    """These are collected once and snapshotted into each session at recording time."""
    created = client.post("/api/patients", json=NEW_PATIENT).json()

    stored = next(
        p for p in client.get("/api/patients").json() if p["patient_id"] == created["patient_id"]
    )

    assert stored["height_cm"] == 182.0
    assert stored["dominant_hand"] == "right"
    assert stored["motion_sickness_susceptibility"] == "low"


def test_update_patient_changes_only_what_was_sent(client: TestClient) -> None:
    created = client.post("/api/patients", json=NEW_PATIENT).json()

    response = client.put(f"/api/patients/{created['patient_id']}", json={"weight_kg": 80.5})

    assert response.status_code == 200
    assert response.json()["weight_kg"] == 80.5
    assert response.json()["display_name"] == "Subject A"


def test_update_unknown_patient_is_404(client: TestClient) -> None:
    assert client.put("/api/patients/nope", json={"weight_kg": 1.0}).status_code == 404


def test_withdraw_consent_flips_the_flag_without_deleting(client: TestClient) -> None:
    """Withdrawal stops new collection; it is not the same act as erasure."""
    created = client.post("/api/patients", json=NEW_PATIENT).json()

    response = client.post(f"/api/patients/{created['patient_id']}/withdraw-consent")

    assert response.status_code == 200
    assert not response.json()["gdpr_consent_given"]
    assert not response.json()["is_anonymized"]


def test_boolean_patient_fields_serialise_as_sqlite_integers(client: TestClient) -> None:
    """Pinned because it is surprising, load-bearing, and easy to "tidy up".

    Patient rows go to the client as raw sqlite3.Row values, so booleans arrive
    as 0 and 1, not false and true. The frontend relies on JavaScript truthiness
    and works either way -- but a repository layer that started returning real
    booleans would change the JSON contract, and any consumer doing a strict
    `=== true` comparison would flip behaviour silently. VRT-11 should make this
    a deliberate decision rather than an accident of the driver.
    """
    created = client.post("/api/patients", json=NEW_PATIENT).json()

    assert created["gdpr_consent_given"] in (0, 1)
    assert created["is_anonymized"] in (0, 1)
    assert not isinstance(created["gdpr_consent_given"], bool)


def test_withdraw_consent_on_unknown_patient_is_404(client: TestClient) -> None:
    assert client.post("/api/patients/nope/withdraw-consent").status_code == 404


def test_soft_delete_anonymises_and_hides_from_the_default_listing(client: TestClient) -> None:
    """Right to erasure: the identifying fields go, the record's shape stays.

    Sessions reference patient_id, so hard-deleting the row would orphan
    research data. Anonymising satisfies erasure while keeping the dataset
    coherent, which is why it is the default.
    """
    created = client.post("/api/patients", json=NEW_PATIENT).json()

    assert client.delete(f"/api/patients/{created['patient_id']}").status_code == 200

    assert client.get("/api/patients").json() == []
    with_erased = client.get("/api/patients", params={"include_anonymized": True}).json()
    assert len(with_erased) == 1
    assert with_erased[0]["is_anonymized"]
    assert with_erased[0]["display_name"] != "Subject A"


def test_hard_delete_removes_the_record_entirely(client: TestClient) -> None:
    created = client.post("/api/patients", json=NEW_PATIENT).json()

    client.delete(f"/api/patients/{created['patient_id']}", params={"hard_delete": True})

    assert client.get("/api/patients", params={"include_anonymized": True}).json() == []


def test_delete_unknown_patient_is_404(client: TestClient) -> None:
    assert client.delete("/api/patients/nope").status_code == 404


def test_patient_writes_survive_an_unreachable_central_server(
    client: TestClient, workstation: Any
) -> None:
    """Every mutation pushes to central best-effort; none may fail on its account.

    The whole suite runs offline, so these all passing is the assertion. Stated
    once, explicitly, because it is a deliberate property: a researcher on a
    disconnected workstation must still be able to enrol and manage subjects.
    """
    created = client.post("/api/patients", json=NEW_PATIENT).json()
    assert (
        client.put(f"/api/patients/{created['patient_id']}", json={"weight_kg": 79.0}).status_code
        == 200
    )
    assert client.post(f"/api/patients/{created['patient_id']}/withdraw-consent").status_code == 200
    assert client.delete(f"/api/patients/{created['patient_id']}").status_code == 200
