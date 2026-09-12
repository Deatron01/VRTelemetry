# tests/unit/test_consent_av_recording.py
"""P-C7 (A/V recording + transcription consent) and its withdrawal scope.

Mirrors test_consent_register.py's fixtures. The property that matters most:
withdrawing SPEECH_RECORDING_ONLY must never look like withdrawing P-C3 --
see WithdrawalScope's own docstring and the bug this guards against in
src/interfaces/api/routers/patients.py (SPEECH_RECORDING_ONLY used to fall
into the branch that sets gdpr_consent_given = 0).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.application.consent import (
    ConsentService,
    ConsentSubmission,
    ConsentValidationError,
    WithdrawalScope,
)
from src.config import ConsentSettings
from src.infrastructure.persistence.consent_repository import ConsentRepository
from src.patients.consent_texts import AV_RECORDING_CONSENT_ID, build_catalogue


@pytest.fixture
def settings_box() -> dict[str, ConsentSettings]:
    return {
        "consent": ConsentSettings(
            study_id="study-a", study_title="Study A", enable_av_recording=True
        )
    }


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


def test_p_c7_appears_only_when_the_feature_is_enabled(tmp_path: Path) -> None:
    off = ConsentService(
        ConsentRepository(tmp_path / "off.db"),
        catalogue_provider=lambda: build_catalogue(ConsentSettings(enable_av_recording=False)),
    )
    assert off.catalogue().item(AV_RECORDING_CONSENT_ID) is None


def test_p_c7_is_required_when_offered(service: ConsentService) -> None:
    item = service.catalogue().item(AV_RECORDING_CONSENT_ID)
    assert item is not None
    assert item.required is True


def test_p_c7_wording_never_mentions_a_stress_score(service: ConsentService) -> None:
    """The addendum's Section 6.2 gate: the score model is not built, so the
    wording participants see must not claim it is."""
    item = service.catalogue().item(AV_RECORDING_CONSENT_ID)
    lowered = item.text.lower()
    for banned in ("stress", "score", "emotion"):
        assert banned not in lowered


def test_av_recording_permitted_reflects_the_given_consent(service: ConsentService) -> None:
    record = service.give("pat-1", _submission(service))
    assert service.av_recording_permitted(record["consent_id"]) is True


def test_declining_p_c7_refuses_the_whole_submission(service: ConsentService) -> None:
    """P-C7 is required, not optional, when offered (addendum Section 3.2):
    a participant who won't agree to it cannot get a consent recorded at all
    by ticking it False, unlike the optional P-C5 research consent."""
    with pytest.raises(ConsentValidationError, match=AV_RECORDING_CONSENT_ID):
        service.give("pat-1", _submission(service, **{AV_RECORDING_CONSENT_ID: False}))


def test_withdrawing_speech_recording_only_does_not_end_the_consent(
    service: ConsentService,
) -> None:
    record = service.give("pat-1", _submission(service))

    affected = service.withdraw("pat-1", WithdrawalScope.SPEECH_RECORDING_ONLY)

    assert affected == [record["consent_id"]]
    assert service.av_recording_permitted(record["consent_id"]) is False
    # The consent as a whole -- P-C3 sensor recording -- is untouched: it
    # still authorises a telemetry-only recording for this participant.
    assert service.require_for_recording("pat-1", None)["consent_id"] == record["consent_id"]


def test_withdrawing_speech_recording_only_leaves_provider_research_alone(
    service: ConsentService,
) -> None:
    record = service.give("pat-1", _submission(service))
    assert service.provider_research_permitted(record["consent_id"])

    service.withdraw("pat-1", WithdrawalScope.SPEECH_RECORDING_ONLY)

    assert service.provider_research_permitted(record["consent_id"]) is True


def test_the_history_reports_av_recording_permitted_per_consent(
    service: ConsentService,
) -> None:
    service.give("pat-1", _submission(service))
    service.withdraw("pat-1", WithdrawalScope.SPEECH_RECORDING_ONLY)

    [consent] = service.history("pat-1")["consents"]
    assert consent["av_recording_permitted"] is False
    assert consent["active"] is True


def test_a_withdrawal_with_nothing_to_withdraw_is_still_on_file(
    service: ConsentService,
) -> None:
    assert service.withdraw("pat-9", WithdrawalScope.SPEECH_RECORDING_ONLY) == []

    [event] = service.history("pat-9")["events"]
    assert event["event_type"] == "av_recording_withdrawn"
    assert event["detail"] == "no active consent to withdraw"
