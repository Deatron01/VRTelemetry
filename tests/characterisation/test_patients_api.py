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

import pytest
from fastapi.testclient import TestClient

NEW_PATIENT_FIELDS = {
    "display_name": "Subject A",
    "biological_sex": "male",
    "height_cm": 182.0,
    "weight_kg": 78.0,
    "dominant_hand": "right",
    "vr_experience_level": "novice",
    "motion_sickness_susceptibility": "low",
}


@pytest.fixture
def new_patient(consent_payload) -> dict[str, Any]:
    """A create-patient body carrying a valid participant consent (GDPR-09)."""
    return {**NEW_PATIENT_FIELDS, "consent": consent_payload()}


def test_list_patients_starts_empty(client: TestClient) -> None:
    assert client.get("/api/patients").json() == []


def test_create_patient_returns_the_stored_record(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    response = client.post("/api/patients", json=new_patient)

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Subject A"
    assert body["gdpr_consent_given"]
    assert body["patient_id"]
    assert not body["is_anonymized"]


def test_create_patient_without_consent_is_refused(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    """A patient record cannot exist without consent. This is the load-bearing rule."""
    body = {k: v for k, v in new_patient.items() if k != "consent"}

    response = client.post("/api/patients", json={**body, "gdpr_consent_given": True})

    assert response.status_code == 403, "a researcher's boolean is no longer consent (GDPR-09)"
    assert client.get("/api/patients").json() == [], "a refused consent must store nothing"


def test_create_patient_requires_a_display_name(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    response = client.post("/api/patients", json={"consent": new_patient["consent"]})

    assert response.status_code == 422


def test_health_profile_fields_round_trip(client: TestClient, new_patient: dict[str, Any]) -> None:
    """These are collected once and snapshotted into each session at recording time."""
    created = client.post("/api/patients", json=new_patient).json()

    stored = next(
        p for p in client.get("/api/patients").json() if p["patient_id"] == created["patient_id"]
    )

    assert stored["height_cm"] == 182.0
    assert stored["dominant_hand"] == "right"
    assert stored["motion_sickness_susceptibility"] == "low"


def test_update_patient_changes_only_what_was_sent(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    created = client.post("/api/patients", json=new_patient).json()

    response = client.put(f"/api/patients/{created['patient_id']}", json={"weight_kg": 80.5})

    assert response.status_code == 200
    assert response.json()["weight_kg"] == 80.5
    assert response.json()["display_name"] == "Subject A"


def test_update_unknown_patient_is_404(client: TestClient) -> None:
    assert client.put("/api/patients/nope", json={"weight_kg": 1.0}).status_code == 404


def test_withdraw_consent_flips_the_flag_without_deleting(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    """Withdrawal stops new collection; it is not the same act as erasure."""
    created = client.post("/api/patients", json=new_patient).json()

    response = client.post(f"/api/patients/{created['patient_id']}/withdraw-consent")

    assert response.status_code == 200
    assert not response.json()["gdpr_consent_given"]
    assert not response.json()["is_anonymized"]


def test_boolean_patient_fields_serialise_as_sqlite_integers(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    """Pinned because it is surprising, load-bearing, and easy to "tidy up".

    Patient rows go to the client as raw sqlite3.Row values, so booleans arrive
    as 0 and 1, not false and true. The frontend relies on JavaScript truthiness
    and works either way -- but a repository layer that started returning real
    booleans would change the JSON contract, and any consumer doing a strict
    `=== true` comparison would flip behaviour silently. VRT-11 should make this
    a deliberate decision rather than an accident of the driver.
    """
    created = client.post("/api/patients", json=new_patient).json()

    assert created["gdpr_consent_given"] in (0, 1)
    assert created["is_anonymized"] in (0, 1)
    assert not isinstance(created["gdpr_consent_given"], bool)


def test_withdraw_consent_on_unknown_patient_is_404(client: TestClient) -> None:
    assert client.post("/api/patients/nope/withdraw-consent").status_code == 404


def test_soft_delete_anonymises_and_hides_from_the_default_listing(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    """Right to erasure: the identifying fields go, the record's shape stays.

    Sessions reference patient_id, so hard-deleting the row would orphan
    research data. Anonymising satisfies erasure while keeping the dataset
    coherent, which is why it is the default.
    """
    created = client.post("/api/patients", json=new_patient).json()

    assert client.delete(f"/api/patients/{created['patient_id']}").status_code == 200

    assert client.get("/api/patients").json() == []
    with_erased = client.get("/api/patients", params={"include_anonymized": True}).json()
    assert len(with_erased) == 1
    assert with_erased[0]["is_anonymized"]
    assert with_erased[0]["display_name"] != "Subject A"


def test_hard_delete_removes_the_record_entirely(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    created = client.post("/api/patients", json=new_patient).json()

    client.delete(f"/api/patients/{created['patient_id']}", params={"hard_delete": True})

    assert client.get("/api/patients", params={"include_anonymized": True}).json() == []


def test_delete_unknown_patient_is_404(client: TestClient) -> None:
    assert client.delete("/api/patients/nope").status_code == 404


def test_patient_writes_survive_an_unreachable_central_server(
    client: TestClient, workstation: Any, new_patient: dict[str, Any]
) -> None:
    """Every mutation pushes to central best-effort; none may fail on its account.

    The whole suite runs offline, so these all passing is the assertion. Stated
    once, explicitly, because it is a deliberate property: a researcher on a
    disconnected workstation must still be able to enrol and manage subjects.
    """
    created = client.post("/api/patients", json=new_patient).json()
    assert (
        client.put(f"/api/patients/{created['patient_id']}", json={"weight_kg": 79.0}).status_code
        == 200
    )
    assert client.post(f"/api/patients/{created['patient_id']}/withdraw-consent").status_code == 200
    assert client.delete(f"/api/patients/{created['patient_id']}").status_code == 200


# --------------------------------------------------------------------------- #
# The consent register (GDPR-09)
# --------------------------------------------------------------------------- #


def test_the_consent_wording_is_served_with_a_hash_per_item(client: TestClient) -> None:
    texts = client.get("/api/consent/texts").json()

    ids = [item["id"] for item in texts["items"]]
    assert {"P-C1", "P-C2", "P-C3", "P-C4", "R-C1", "R-C2"} <= set(ids)
    assert all(len(item["sha256"]) == 64 for item in texts["items"])
    assert texts["configured"] is False, "the defaults are placeholders and must say so"


def test_creating_a_patient_records_the_participants_consent(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    body = client.post("/api/patients", json=new_patient).json()

    consent = body["consent"]
    assert consent["consent_id"]
    assert consent["choices"]["P-C3"] is True
    assert len(consent["withdrawal_code"].replace("-", "")) == 10
    history = client.get(f"/api/patients/{body['patient_id']}/consents").json()
    assert [c["consent_id"] for c in history["consents"]] == [consent["consent_id"]]
    assert "withdrawal_code_sha256" not in history["consents"][0]
    assert [e["event_type"] for e in history["events"]] == ["given"]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda c: c["choices"].update({"P-C3": False}), "P-C3"),
        (lambda c: c["researcher_confirmations"].update({"R-C1": False}), "R-C1"),
        (lambda c: c["displayed_sha256"].update({"P-C4": "0" * 64}), "not the current wording"),
        (lambda c: c.update({"text_version": "1.0"}), "wording has changed"),
        (lambda c: c["choices"].pop("P-C1"), "P-C1 was not answered"),
    ],
)
def test_an_invalid_consent_is_refused_and_stores_nothing(
    client: TestClient, new_patient: dict[str, Any], mutate: Any, reason: str
) -> None:
    mutate(new_patient["consent"])

    response = client.post("/api/patients", json=new_patient)

    assert response.status_code == 403
    assert reason in response.json()["detail"]
    assert client.get("/api/patients", params={"include_anonymized": True}).json() == []


def test_a_non_boolean_answer_is_not_an_affirmative_act(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    new_patient["consent"]["choices"]["P-C3"] = "yes"

    assert client.post("/api/patients", json=new_patient).status_code == 422


def test_the_optional_research_consent_may_be_declined(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    new_patient["consent"]["choices"]["P-C5"] = False

    body = client.post("/api/patients", json=new_patient).json()

    assert body["consent"]["choices"]["P-C5"] is False


def test_a_participant_who_withdrew_can_consent_again(
    client: TestClient, new_patient: dict[str, Any], consent_payload: Any
) -> None:
    created = client.post("/api/patients", json=new_patient).json()
    patient_id = created["patient_id"]
    client.post(f"/api/patients/{patient_id}/withdraw-consent")

    response = client.post(f"/api/patients/{patient_id}/consents", json=consent_payload())

    assert response.status_code == 200
    patient = next(p for p in client.get("/api/patients").json() if p["patient_id"] == patient_id)
    assert patient["gdpr_consent_given"] == 1
    assert patient["gdpr_consent_withdrawn_at"] is None
    history = client.get(f"/api/patients/{patient_id}/consents").json()
    assert [c["active"] for c in history["consents"]] == [True, False]


def test_withdrawing_only_the_research_consent_keeps_the_participant_enrolled(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    created = client.post("/api/patients", json=new_patient).json()

    response = client.post(
        f"/api/patients/{created['patient_id']}/withdraw-consent",
        json={"scope": "PROVIDER_RESEARCH_ONLY"},
    )

    assert response.status_code == 200
    assert response.json()["gdpr_consent_given"] == 1
    [consent] = client.get(f"/api/patients/{created['patient_id']}/consents").json()["consents"]
    assert consent["active"] is True
    assert consent["provider_research_permitted"] is False


def test_a_withdrawal_code_finds_the_participant(
    client: TestClient, new_patient: dict[str, Any]
) -> None:
    created = client.post("/api/patients", json=new_patient).json()
    code = created["consent"]["withdrawal_code"]

    found = client.post("/api/consent/withdrawal-code", json={"code": code.lower()}).json()

    assert found["patient_id"] == created["patient_id"]
    assert (
        client.post("/api/consent/withdrawal-code", json={"code": "NOPE0-00000"}).status_code == 404
    )
