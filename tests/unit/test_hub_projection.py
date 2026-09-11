# tests/unit/test_hub_projection.py
"""What of a participant may leave the laboratory (GDPR-11).

Three layers are pinned here, in the order data travels:

1. the pure projection functions;
2. the two workstation clients, which must project before sending *and* before
   queueing -- a queue that holds the full record is a second copy of exactly
   what was supposed to stay behind;
3. the hub, which projects again on receipt and scrubs rows written before any
   of this existed.

The assertions are about absence. "The hub received a patient" proves nothing;
"the hub received no name, reference, birth date or free text" is the claim.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.domain.hub_projection import (
    HUB_EXCLUDED_METADATA_KEYS,
    age_from_date_of_birth,
    project_patient_for_hub,
    project_session_metadata_for_hub,
)

IDENTIFYING = {
    "display_name": "Anna Kovács",
    "external_ref": "HOSP-77812",
    "date_of_birth": "1990-06-15",
    "notes": "Anna's sister also participates",
    "vision_impairment": "left-eye amblyopia",
    "relevant_health_conditions": "epilepsy, controlled",
}

PATIENT = {
    "patient_id": "pat-1",
    **IDENTIFYING,
    "biological_sex": "female",
    "age_years": 20,
    "height_cm": 168.0,
    "weight_kg": 61.0,
    "dominant_hand": "right",
    "vision_correction": "glasses",
    "motion_sickness_susceptibility": "mild",
    "gdpr_consent_given": 1,
    "gdpr_consent_version": "2.0",
    "is_anonymized": 0,
}

TODAY = date(2026, 9, 11)


def _assert_no_identifiers(value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False)
    for secret in IDENTIFYING.values():
        assert secret not in text, f"{secret!r} left the workstation: {text}"


# --------------------------------------------------------------------------- #
# The functions
# --------------------------------------------------------------------------- #


def test_the_patient_projection_keeps_covariates_and_drops_identifiers() -> None:
    projected = project_patient_for_hub(PATIENT, TODAY)

    _assert_no_identifiers(projected)
    assert projected["patient_id"] == "pat-1"
    assert projected["height_cm"] == 168.0
    assert projected["gdpr_consent_version"] == "2.0"


def test_age_is_derived_from_the_birth_date_so_the_date_itself_can_stay() -> None:
    assert project_patient_for_hub(PATIENT, TODAY)["age_years"] == 36


def test_without_a_birth_date_the_recorded_age_is_kept() -> None:
    patient = {**PATIENT, "date_of_birth": ""}

    assert project_patient_for_hub(patient, TODAY)["age_years"] == 20


def test_an_unknown_field_is_not_sent_by_default() -> None:
    """Allowlist, not denylist: a column added next month stays local until someone decides."""
    projected = project_patient_for_hub({**PATIENT, "blood_type": "A+"}, TODAY)

    assert "blood_type" not in projected


@pytest.mark.parametrize(
    ("dob", "expected"),
    [("1990-06-15", 36), ("1990/09/12", 35), ("2026-09-11", 0), ("garbage", None), ("", None)],
)
def test_age_from_date_of_birth(dob: str, expected: int | None) -> None:
    assert age_from_date_of_birth(dob, TODAY) == expected


def test_session_metadata_loses_identifiers_at_any_depth() -> None:
    metadata = {
        "session_id": "s1",
        "M-IV_Static_Metadata": {"subject_id": "pat-1", "vision_impairment": "amblyopia"},
        "S-IX_System_Profile": {"hostname": "DR-KOVACS-PC", "os_user": "akovacs", "cpu": "x"},
        "list": [{"display_name": "Anna"}],
    }

    projected = project_session_metadata_for_hub(metadata)

    assert projected["M-IV_Static_Metadata"] == {"subject_id": "pat-1"}
    assert projected["S-IX_System_Profile"] == {"cpu": "x"}
    assert projected["list"] == [{}]
    assert metadata["S-IX_System_Profile"]["hostname"] == "DR-KOVACS-PC", "input was mutated"


def test_an_embedded_json_document_is_projected_too() -> None:
    """`session_metadata.raw_json` is the whole engine context as one string."""
    row = {
        "session_id": "s1",
        "hostname": "DR-KOVACS-PC",
        "raw_json": json.dumps({"S-IX_System_Profile": {"os_user": "akovacs", "cpu": "x"}}),
    }

    projected = project_session_metadata_for_hub(row)

    assert "hostname" not in projected
    assert json.loads(projected["raw_json"]) == {"S-IX_System_Profile": {"cpu": "x"}}


def test_an_embedded_document_that_cannot_be_parsed_is_dropped() -> None:
    """It cannot be inspected, so it cannot be shown to be safe."""
    assert "raw_json" not in project_session_metadata_for_hub({"raw_json": "{not json"})


def test_the_denylist_names_the_researcher_identifiers() -> None:
    assert {"hostname", "os_user"} <= HUB_EXCLUDED_METADATA_KEYS


# --------------------------------------------------------------------------- #
# The workstation clients
# --------------------------------------------------------------------------- #


class _CapturingHttp:
    """Records every request body and answers 200, like a hub that accepted it."""

    def __init__(self) -> None:
        import requests

        self.RequestException = requests.RequestException
        self.bodies: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.bodies.append({"url": url, **kwargs})
        return _Ok()

    def get(self, url: str, *_: Any, **__: Any) -> Any:  # pragma: no cover - unused
        raise AssertionError(url)

    put = delete = get


class _Ok:
    status_code = 200
    text = "ok"

    def json(self) -> dict[str, Any]:
        return {"ok": True}


@pytest.fixture
def cache(tmp_path: Path):
    from src.license_service.local_cache import LocalLicenseCache

    cache = LocalLicenseCache(tmp_path / "license_cache.db")
    cache.save(
        activation_id="act-1",
        license_key="KEY-0001",
        hardware_fingerprint="fp",
        license_id="lic-1",
        machine_label="bench",
    )
    return cache


def test_the_patient_sync_client_sends_only_the_projection(cache) -> None:
    from src.storage.patient_sync_client import PatientSyncClient

    http = _CapturingHttp()
    client = PatientSyncClient("https://hub.test", cache, http=http)

    assert client.sync_patient(dict(PATIENT))["ok"]

    sent = http.bodies[0]["json"]["patient"]
    _assert_no_identifiers(sent)
    assert sent["patient_id"] == "pat-1"


def test_a_queued_patient_sync_holds_only_the_projection(cache) -> None:
    from src.storage.patient_sync_client import PatientSyncClient

    client = PatientSyncClient("", cache, http=_CapturingHttp())  # unconfigured: queues

    client.sync_patient(dict(PATIENT))

    queued = cache.list_pending_patient_syncs()
    assert len(queued) == 1
    _assert_no_identifiers(json.loads(queued[0]["payload_json"]))


def test_the_questionnaire_resync_sends_no_host_or_free_text(cache) -> None:
    """`update_remote_metadata` is handed the full local session row."""
    from src.storage.session_uploader import SessionUploader

    http = _CapturingHttp()
    uploader = SessionUploader("https://hub.test", cache, http=http)
    row = {
        "session_id": "s1",
        "hostname": "DR-KOVACS-PC",
        "os_user": "akovacs",
        "vision_impairment": "amblyopia",
        "raw_json": json.dumps({"display_name": "Anna Kovács"}),
        "ssq_total_severity": 12.0,
    }

    uploader.update_remote_metadata("s1", row)

    sent = json.loads(http.bodies[0]["data"]["metadata_json"])
    assert sent["ssq_total_severity"] == 12.0
    assert "hostname" not in sent and "os_user" not in sent and "vision_impairment" not in sent
    assert "Anna" not in sent["raw_json"]


# --------------------------------------------------------------------------- #
# The hub
# --------------------------------------------------------------------------- #


@pytest.fixture
def hub(tmp_path: Path):
    from src.central_server.data_manager import CentralDataManager
    from src.central_server.data_schema import initialize_data_schema

    db = tmp_path / "central_data.db"
    initialize_data_schema(db)
    return CentralDataManager(db_path=db, storage_root=tmp_path / "CentralStorage")


def test_the_hub_stores_no_identifiers_even_from_an_old_client(hub) -> None:
    """Defence in depth: a workstation that predates the projection sends everything."""
    hub.upsert_patient(license_id="lic-1", activation_id="act-1", patient=dict(PATIENT))

    [stored] = hub.list_patients("lic-1")
    for column in IDENTIFYING:
        assert stored[column] is None, f"{column} was stored"
    _assert_no_identifiers(json.loads(stored["raw_json"]))
    assert stored["height_cm"] == 168.0


def test_the_hub_scrubs_rows_written_before_the_projection(tmp_path: Path) -> None:
    from src.central_server.data_schema import initialize_data_schema, scrub_identifying_data

    db = tmp_path / "central_data.db"
    initialize_data_schema(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO synced_patients
               (patient_id, license_id, display_name, external_ref, date_of_birth, notes,
                vision_impairment, relevant_health_conditions, raw_json)
               VALUES ('pat-1', 'lic-1', ?, ?, ?, ?, ?, ?, ?)""",
            (
                IDENTIFYING["display_name"],
                IDENTIFYING["external_ref"],
                IDENTIFYING["date_of_birth"],
                IDENTIFYING["notes"],
                IDENTIFYING["vision_impairment"],
                IDENTIFYING["relevant_health_conditions"],
                json.dumps(PATIENT),
            ),
        )
        conn.execute(
            """INSERT INTO uploaded_sessions
               (upload_id, session_id, license_id, activation_id, subject_id, patient_id,
                original_filename, storage_path, sha256_checksum, metadata_json)
               VALUES ('u1', 's1', 'lic-1', 'act-1', ?, 'pat-1', 'f', 'p', 'c', ?)""",
            (IDENTIFYING["display_name"], json.dumps({"hostname": "DR-KOVACS-PC"})),
        )

    with sqlite3.connect(db) as conn:
        assert scrub_identifying_data(conn) >= 3
        assert scrub_identifying_data(conn) == 0, "the scrub must be idempotent"
        dump = [list(r) for r in conn.execute("SELECT * FROM synced_patients")]
        dump += [list(r) for r in conn.execute("SELECT * FROM uploaded_sessions")]

    _assert_no_identifiers(dump)
    assert "DR-KOVACS-PC" not in json.dumps(dump)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT subject_id FROM uploaded_sessions").fetchone() == ("pat-1",)
        assert conn.execute("SELECT age_years FROM synced_patients").fetchone()[0] >= 36
