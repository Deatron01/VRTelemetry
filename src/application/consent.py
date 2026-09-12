# src/application/consent.py
"""Participant consent: validating it, recording it, and relying on it (GDPR-09).

The rules, each with the reason it exists:

* **The participant's choices, not the researcher's.** Every participant
  checkbox in the catalogue must be answered, every required one must be
  ticked, and the two researcher confirmations -- that the participant ticked
  the boxes themselves, and understood them -- must be given. The researcher's
  confirmation is recorded *beside* the participant's consent; it never
  replaces it (Art. 9(2)(a), Art. 7(1) GDPR).
* **The wording that was shown is the wording that was agreed to.** The client
  returns the SHA-256 of each text it displayed; a mismatch with the current
  catalogue is refused, so a stored record proves which words were on screen.
* **Consent is specific to a study and a wording version.** A recording is
  authorised only by an active consent for the configured study under the
  current :data:`~src.patients.consent_texts.CONSENT_TEXT_VERSION`.
* **Withdrawal is an event, not an edit** (Art. 7(3)). Three scopes, chosen by
  the participant: stop future recordings only; stop and erase everything; or
  withdraw only the optional provider-research consent. Erasure itself is
  carried out by :mod:`src.application.erasure`.
* **The withdrawal code is shown once and stored only as a hash.** It lets a
  participant who has left the lab identify their own data later without the
  laboratory having to keep a contact detail for them.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.application.ports import ConsentStore
from src.core.exceptions import GDPRConsentError
from src.patients.consent_texts import (
    AV_RECORDING_CONSENT_ID,
    PROVIDER_RESEARCH_CONSENT_ID,
    RECORDING_CONSENT_ID,
    RESEARCHER,
    ConsentCatalogue,
)
from src.utils.clock import utc_now_iso

#: Unambiguous characters for a code a participant may have to read out or type.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 10


class ConsentValidationError(GDPRConsentError):
    """A consent submission that cannot be accepted, with the reason."""


class WithdrawalScope(str, Enum):
    """What the participant asked for when withdrawing."""

    #: Stop all future recordings and erase everything recorded so far.
    ALL_DELETE = "ALL_DELETE"
    #: Stop all future recordings; data already collected stays in the study.
    FUTURE_ONLY = "FUTURE_ONLY"
    #: Withdraw only the optional provider-research consent (P-C5).
    PROVIDER_RESEARCH_ONLY = "PROVIDER_RESEARCH_ONLY"
    #: Withdraw only the A/V recording, transcription consent (P-C7). Deletes
    #: the recording, transcript and derived scores for the participant's
    #: sessions (see ErasureService.erase_av_recordings); telemetry recording
    #: under P-C3 is unaffected. Addendum Section 3.4.
    SPEECH_RECORDING_ONLY = "SPEECH_RECORDING_ONLY"


@dataclass(frozen=True)
class ConsentSubmission:
    """What the consent screen sends back."""

    text_version: str
    choices: dict[str, bool]
    displayed_sha256: dict[str, str]
    researcher_confirmations: dict[str, bool]
    language: str = "en"
    method: str = "on-screen-participant"


def hash_withdrawal_code(code: str) -> str:
    """The stored form of a withdrawal code. Case and separators are ignored."""
    normalised = "".join(ch for ch in code.upper() if ch.isalnum())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _new_withdrawal_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


class ConsentService:
    """The only way consent is given, checked, or withdrawn."""

    def __init__(
        self,
        repository: ConsentStore,
        catalogue_provider: Callable[[], ConsentCatalogue],
    ) -> None:
        self.repository = repository
        self._catalogue_provider = catalogue_provider

    def catalogue(self) -> ConsentCatalogue:
        """The wording for the study currently configured."""
        return self._catalogue_provider()

    # --- giving consent -----------------------------------------------------

    def validate(self, submission: ConsentSubmission) -> ConsentCatalogue:
        """Check a submission against the current catalogue.

        Returns:
            The catalogue it was validated against.

        Raises:
            ConsentValidationError: naming the first problem found.
        """
        catalogue = self.catalogue()
        if submission.text_version != catalogue.text_version:
            raise ConsentValidationError(
                f"The consent wording has changed (shown: v{submission.text_version}, current: "
                f"v{catalogue.text_version}). Reload the consent screen and ask again."
            )

        known = {item.id for item in catalogue.items}
        unknown = (set(submission.choices) | set(submission.researcher_confirmations)) - known
        if unknown:
            raise ConsentValidationError(f"Unknown consent items: {sorted(unknown)}")

        for item in catalogue.items:
            answers = (
                submission.researcher_confirmations
                if item.group == RESEARCHER
                else submission.choices
            )
            if submission.displayed_sha256.get(item.id) != item.sha256:
                raise ConsentValidationError(
                    f"The text shown for {item.id} is not the current wording. Reload the "
                    f"consent screen and ask again."
                )
            if item.id not in answers or not isinstance(answers[item.id], bool):
                raise ConsentValidationError(f"{item.id} was not answered.")
            if item.required and not answers[item.id]:
                who = "The researcher" if item.group == RESEARCHER else "The participant"
                raise ConsentValidationError(
                    f"{who} did not agree to {item.id} ({item.label}), which is required. "
                    f"Nothing has been recorded."
                )
        return catalogue

    def give(
        self,
        patient_id: str,
        submission: ConsentSubmission,
        *,
        researcher_user: str | None = None,
        workstation: str | None = None,
    ) -> dict[str, Any]:
        """Validate and record a consent.

        Returns:
            The stored record, plus ``withdrawal_code`` -- the only time the
            code exists in clear. Show it to the participant; it is not stored.
        """
        catalogue = self.validate(submission)
        code = _new_withdrawal_code()
        participant_ids = [i.id for i in catalogue.items if i.group != RESEARCHER]
        researcher_ids = [i.id for i in catalogue.items if i.group == RESEARCHER]
        record: dict[str, Any] = {
            "consent_id": str(uuid.uuid4()),
            "patient_id": patient_id,
            "study_id": catalogue.study_id,
            "study_title": catalogue.study_title,
            "text_version": catalogue.text_version,
            "notice_version": catalogue.notice_version,
            "language": submission.language,
            "method": submission.method,
            "choices": {i: submission.choices[i] for i in participant_ids},
            "text_sha256": {i.id: i.sha256 for i in catalogue.items},
            "researcher": {i: submission.researcher_confirmations[i] for i in researcher_ids},
            "researcher_user": researcher_user,
            "workstation": workstation,
            "withdrawal_code_sha256": hash_withdrawal_code(code),
            "given_at_utc": utc_now_iso(),
        }
        self.repository.insert_consent(record)
        stored = self.repository.get(record["consent_id"]) or record
        return {**stored, "withdrawal_code": code}

    # --- relying on consent -------------------------------------------------

    def active_consent(self, patient_id: str) -> dict[str, Any] | None:
        """The newest consent that currently authorises recording, if any."""
        catalogue = self.catalogue()
        for record in self.repository.list_for_patient(patient_id):
            if self._authorises_recording(record, catalogue):
                return record
        return None

    def _authorises_recording(self, record: dict[str, Any], catalogue: ConsentCatalogue) -> bool:
        return (
            record["study_id"] == catalogue.study_id
            and record["text_version"] == catalogue.text_version
            and bool(record["choices"].get(RECORDING_CONSENT_ID))
            and not self.repository.is_ended(record["consent_id"])
        )

    def require_for_recording(self, patient_id: str, consent_id: str | None) -> dict[str, Any]:
        """The consent a recording will be made under, or the reason there is none.

        Args:
            patient_id: The participant about to be recorded.
            consent_id: The consent the client selected. None means "the
                participant's current consent", which is what the desktop app
                sends when the participant has exactly one.

        Raises:
            ConsentValidationError: with a message the UI can show verbatim.
        """
        catalogue = self.catalogue()
        if consent_id is None:
            record = self.active_consent(patient_id)
            if record is None:
                raise ConsentValidationError(
                    "Recording can't start: no valid consent is recorded for this participant "
                    f'for the study "{catalogue.study_title}" (wording v{catalogue.text_version}). '
                    "Ask the participant to complete the consent screen."
                )
            return record

        record = self.repository.get(consent_id)
        if record is None or record["patient_id"] != patient_id:
            raise ConsentValidationError("That consent does not belong to this participant.")
        if self.repository.is_ended(consent_id):
            raise ConsentValidationError(
                "This participant withdrew that consent. They need to give new consent before "
                "any further recording."
            )
        if record["study_id"] != catalogue.study_id:
            raise ConsentValidationError(
                f'This consent covers the study "{record["study_title"]}", not '
                f'"{catalogue.study_title}". Consent is needed for this study before recording.'
            )
        if record["text_version"] != catalogue.text_version:
            raise ConsentValidationError(
                f"Consent was given to wording v{record['text_version']}, which has since "
                f"changed to v{catalogue.text_version}. Please ask the participant to review "
                f"and consent again."
            )
        if not record["choices"].get(RECORDING_CONSENT_ID):
            raise ConsentValidationError("This consent does not include sensor recording.")
        return record

    def provider_research_permitted(self, consent_id: str) -> bool:
        """Whether the optional provider-research consent is given and not withdrawn."""
        record = self.repository.get(consent_id)
        return bool(
            record
            and record["choices"].get(PROVIDER_RESEARCH_CONSENT_ID)
            and not self.repository.is_ended(consent_id)
            and not self.repository.is_research_withdrawn(consent_id)
        )

    def av_recording_permitted(self, consent_id: str) -> bool:
        """Whether this consent currently authorises A/V recording (P-C7).

        Checked by the recording route before starting a
        :class:`~src.av_recording.session_recorder.SessionRecorder` alongside
        the telemetry engine -- never by asking whether the *feature* is
        enabled, which says nothing about what this particular participant
        agreed to.
        """
        record = self.repository.get(consent_id)
        return bool(
            record
            and record["choices"].get(AV_RECORDING_CONSENT_ID)
            and not self.repository.is_ended(consent_id)
            and not self.repository.is_av_recording_withdrawn(consent_id)
        )

    # --- withdrawing ----------------------------------------------------------

    def withdraw(self, patient_id: str, scope: WithdrawalScope) -> list[str]:
        """Record a withdrawal against every consent it applies to.

        Returns:
            The ids of the consents affected. Empty when there was nothing to
            withdraw -- still a valid request, and still recorded as an event
            so the participant's request is on file.
        """
        now = utc_now_iso()
        records = self.repository.list_for_patient(patient_id)
        if scope is WithdrawalScope.PROVIDER_RESEARCH_ONLY:
            affected = [
                r["consent_id"]
                for r in records
                if r["choices"].get(PROVIDER_RESEARCH_CONSENT_ID)
                and not self.repository.is_research_withdrawn(r["consent_id"])
            ]
            event_type = "research_withdrawn"
        elif scope is WithdrawalScope.SPEECH_RECORDING_ONLY:
            affected = [
                r["consent_id"]
                for r in records
                if r["choices"].get(AV_RECORDING_CONSENT_ID)
                and not self.repository.is_av_recording_withdrawn(r["consent_id"])
            ]
            event_type = "av_recording_withdrawn"
        else:
            affected = [
                r["consent_id"] for r in records if not self.repository.is_ended(r["consent_id"])
            ]
            event_type = "withdrawn"

        for consent_id in affected:
            self.repository.insert_event(
                patient_id=patient_id,
                consent_id=consent_id,
                event_type=event_type,
                scope=scope.value,
                occurred_at_utc=now,
            )
        if not affected:
            self.repository.insert_event(
                patient_id=patient_id,
                event_type=event_type,
                scope=scope.value,
                occurred_at_utc=now,
                detail="no active consent to withdraw",
            )
        return affected

    def record_erasure(self, patient_id: str, detail: str) -> None:
        """Append the fact of an erasure to the participant's consent history."""
        self.repository.insert_event(
            patient_id=patient_id,
            event_type="erased",
            occurred_at_utc=utc_now_iso(),
            detail=detail,
        )

    def find_by_withdrawal_code(self, code: str) -> dict[str, Any] | None:
        """The consent a participant's withdrawal code belongs to, if any."""
        return self.repository.find_by_withdrawal_code_hash(hash_withdrawal_code(code))

    def history(self, patient_id: str) -> dict[str, Any]:
        """Every consent and every event for one participant, for display."""
        catalogue = self.catalogue()
        consents = []
        for record in self.repository.list_for_patient(patient_id):
            public = {k: v for k, v in record.items() if k != "withdrawal_code_sha256"}
            public["active"] = self._authorises_recording(record, catalogue)
            public["provider_research_permitted"] = self.provider_research_permitted(
                record["consent_id"]
            )
            public["av_recording_permitted"] = self.av_recording_permitted(record["consent_id"])
            consents.append(public)
        return {
            "patient_id": patient_id,
            "consents": consents,
            "events": self.repository.events_for_patient(patient_id),
        }
