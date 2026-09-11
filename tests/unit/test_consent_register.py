# tests/unit/test_consent_register.py
"""The consent register below the HTTP layer (GDPR-09).

The route tests in tests/characterisation/test_patients_api.py cover the
behaviour a client sees. These cover the properties a client cannot see and a
supervisory authority would ask about: that the evidence cannot be rewritten,
that the withdrawal code is not stored, and that a consent authorises only the
study and wording it was given for.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.application.consent import (
    ConsentService,
    ConsentSubmission,
    ConsentValidationError,
    WithdrawalScope,
    hash_withdrawal_code,
)
from src.config import ConsentSettings
from src.infrastructure.persistence.consent_repository import ConsentRepository
from src.patients.consent_texts import CONSENT_TEXT_VERSION, build_catalogue


@pytest.fixture
def settings_box() -> dict[str, ConsentSettings]:
    """Mutable holder, so a test can change the configured study mid-way."""
    return {"consent": ConsentSettings(study_id="study-a", study_title="Study A")}


@pytest.fixture
def service(tmp_path: Path, settings_box) -> ConsentService:
    return ConsentService(
        ConsentRepository(tmp_path / "patients.db"),
        catalogue_provider=lambda: build_catalogue(settings_box["consent"]),
    )


def _submission(service: ConsentService, **choices: bool) -> ConsentSubmission:
    catalogue = service.catalogue()
    answers = {i.id: True for i in catalogue.items if i.group != "researcher"}
    answers.update(choices)
    return ConsentSubmission(
        text_version=catalogue.text_version,
        choices=answers,
        displayed_sha256={i.id: i.sha256 for i in catalogue.items},
        researcher_confirmations={"R-C1": True, "R-C2": True},
    )


def test_a_consent_is_recorded_with_the_hash_of_every_text_shown(service) -> None:
    record = service.give("pat-1", _submission(service), researcher_user="r@lab.org")

    catalogue = service.catalogue()
    assert record["text_sha256"] == {i.id: i.sha256 for i in catalogue.items}
    assert record["text_version"] == CONSENT_TEXT_VERSION
    assert record["researcher_user"] == "r@lab.org"
    assert record["researcher"] == {"R-C1": True, "R-C2": True}


def test_the_withdrawal_code_is_returned_once_and_stored_only_as_a_hash(
    service, tmp_path: Path
) -> None:
    record = service.give("pat-1", _submission(service))
    code = record["withdrawal_code"]

    with sqlite3.connect(tmp_path / "patients.db") as conn:
        dump = "\n".join(str(row) for row in conn.execute("SELECT * FROM consent_records"))
    assert code not in dump and code.replace("-", "") not in dump
    assert hash_withdrawal_code(code) in dump
    assert service.find_by_withdrawal_code(code.lower().replace("-", " "))["patient_id"] == "pat-1"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE consent_records SET choices_json = '{}'",
        "DELETE FROM consent_records",
        "UPDATE consent_events SET event_type = 'given'",
        "DELETE FROM consent_events",
    ],
)
def test_consent_evidence_cannot_be_rewritten_even_with_raw_sql(
    service, tmp_path: Path, statement: str
) -> None:
    """Enforced by SQLite triggers, not by the application's good behaviour."""
    service.give("pat-1", _submission(service))
    service.withdraw("pat-1", WithdrawalScope.FUTURE_ONLY)

    with (
        sqlite3.connect(tmp_path / "patients.db") as conn,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        conn.execute(statement)


def test_a_consent_authorises_only_its_own_study(service, settings_box) -> None:
    record = service.give("pat-1", _submission(service))
    assert service.require_for_recording("pat-1", record["consent_id"])

    settings_box["consent"] = ConsentSettings(study_id="study-b", study_title="Study B")

    with pytest.raises(ConsentValidationError, match="Study A"):
        service.require_for_recording("pat-1", record["consent_id"])
    with pytest.raises(ConsentValidationError, match="no valid consent"):
        service.require_for_recording("pat-1", None)


def test_withdrawal_ends_recording_but_leaves_the_record(service) -> None:
    record = service.give("pat-1", _submission(service))

    assert service.withdraw("pat-1", WithdrawalScope.FUTURE_ONLY) == [record["consent_id"]]

    with pytest.raises(ConsentValidationError, match="withdrew"):
        service.require_for_recording("pat-1", record["consent_id"])
    history = service.history("pat-1")
    assert [e["event_type"] for e in history["events"]] == ["given", "withdrawn"]
    assert history["consents"][0]["active"] is False


def test_withdrawing_research_consent_does_not_stop_recording(service) -> None:
    record = service.give("pat-1", _submission(service))
    assert service.provider_research_permitted(record["consent_id"])

    service.withdraw("pat-1", WithdrawalScope.PROVIDER_RESEARCH_ONLY)

    assert not service.provider_research_permitted(record["consent_id"])
    assert service.require_for_recording("pat-1", None)["consent_id"] == record["consent_id"]


def test_a_withdrawal_with_nothing_to_withdraw_is_still_on_file(service) -> None:
    assert service.withdraw("pat-9", WithdrawalScope.FUTURE_ONLY) == []

    [event] = service.history("pat-9")["events"]
    assert event["detail"] == "no active consent to withdraw"


def test_the_sensors_named_are_the_sensors_configured() -> None:
    text: Any = build_catalogue(
        ConsentSettings(records_heart_rate=False, records_voice_level=False)
    ).item("P-C3")

    assert "heart rate" not in text.text
    assert "voice" not in text.text


def test_the_research_consent_is_offered_only_when_the_lab_allows_it() -> None:
    catalogue = build_catalogue(ConsentSettings(offer_provider_research=False))

    assert catalogue.item("P-C5") is None


def test_a_configured_study_reports_itself_configured() -> None:
    catalogue = build_catalogue(
        ConsentSettings(
            laboratory_name="VR Lab",
            laboratory_contact="lab@example.org",
            provider_name="Provider Kft.",
            study_title="Balance",
            study_purpose="to study balance",
            retention="5 years after the study",
        )
    )

    assert catalogue.configured is True
    assert "VR Lab" in str(catalogue.item("P-C3"))
