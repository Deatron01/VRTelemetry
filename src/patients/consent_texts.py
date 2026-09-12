# src/patients/consent_texts.py
"""The exact words a participant consents to (GDPR-09).

Until this module, "consent" in VRTelemetry was one checkbox ticked by the
researcher -- ``gdpr_consent_given`` on the patient form, ``gdpr_consent`` on
the recording request, ``--gdpr-consent`` on the command line. The README said
of the last one: *"the flag is the record that consent was obtained"*. It
records that someone typed it. Article 9(2)(a) GDPR requires the participant's
own *explicit* consent, and Article 7(1) requires the controller to be able to
*demonstrate* it: who agreed, to what wording, when.

So the wording lives here, in one place, and is served to the desktop app by
``GET /api/consent/texts``. The app renders it verbatim and sends back the
SHA-256 of every text it displayed; the server refuses a consent whose hashes do
not match the current wording. That is what lets a stored consent record prove
which words were on the screen -- not merely that a box was ticked somewhere.

Study-specific values (laboratory, study title, purpose, retention) come from
:class:`~src.config.settings.ConsentSettings`. A change to any of them changes
the hashes, so a screen left open across a configuration change cannot submit
a consent to wording it did not show.

The wording follows the "Consent Texts (UI Copy)" legal draft. Changing it
materially means bumping :data:`CONSENT_TEXT_VERSION`; recordings then require
fresh consent, which is the correct consequence of changing what people agreed
to.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from src.config.settings import ConsentSettings

#: Version of the wording below. 1.0 was the single researcher checkbox.
CONSENT_TEXT_VERSION = "2.0"

PARTICIPANT_REQUIRED = "participant_required"
PARTICIPANT_OPTIONAL = "participant_optional"
RESEARCHER = "researcher"

#: The consent that authorises recording sensor data at all.
RECORDING_CONSENT_ID = "P-C3"
#: The optional consent for the provider's de-identified research dataset.
PROVIDER_RESEARCH_CONSENT_ID = "P-C5"
#: Explicit consent to A/V recording (headset-view video + speech audio) and
#: transcription (the A/V recording, transcription & stress-inference
#: addendum, Sep 2026). Required, not optional, when offered at all --
#: ``ConsentSettings.enable_av_recording`` is what decides whether it appears.
#: See that setting's docstring for why the addendum's stress-score clause is
#: not part of this wording.
AV_RECORDING_CONSENT_ID = "P-C7"


@dataclass(frozen=True)
class ConsentItem:
    """One checkbox: its stable id, whether it is required, and its exact text."""

    id: str
    group: str
    required: bool
    label: str
    text: str

    @property
    def sha256(self) -> str:
        """Hash of the exact wording, as displayed. The id is part of it."""
        return hashlib.sha256(f"{self.id}\n{self.text}".encode()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "required": self.required,
            "label": self.label,
            "text": self.text,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ConsentCatalogue:
    """Everything the consent screens show, for the study currently configured."""

    text_version: str
    notice_version: str
    notice_url: str
    study_id: str
    study_title: str
    laboratory_name: str
    provider_name: str
    language: str
    items: tuple[ConsentItem, ...]
    short_notice: dict[str, Any] = field(default_factory=dict)
    configured: bool = True

    def item(self, item_id: str) -> ConsentItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text_version": self.text_version,
            "notice_version": self.notice_version,
            "notice_url": self.notice_url,
            "study_id": self.study_id,
            "study_title": self.study_title,
            "laboratory_name": self.laboratory_name,
            "provider_name": self.provider_name,
            "language": self.language,
            "configured": self.configured,
            "short_notice": self.short_notice,
            "items": [i.as_dict() for i in self.items],
        }


def _sensor_phrase(cfg: ConsentSettings) -> str:
    phrase = "my head and hand movements, my eye movements and pupil size"
    if cfg.records_heart_rate:
        phrase += ", my heart rate"
    if cfg.records_voice_level:
        phrase += " and the loudness of my voice (not what I say)"
    return phrase


def _recorded_list(cfg: ConsentSettings) -> list[str]:
    recorded = [
        "Your head and hand movements",
        "Where you look, how your eyes move, and the size of your pupils",
    ]
    if cfg.records_heart_rate:
        recorded.append("Your heart rate")
    if cfg.records_voice_level:
        recorded.append("How loud your voice is (not what you say)")
    recorded.append(
        "Answers you give about your age, body, eyesight and health, "
        "and how you felt during the session"
    )
    if cfg.enable_av_recording:
        recorded.append(
            "A recording of what you see in the headset and of your voice "
            "while you speak during the task"
        )
        recorded.append("An automatic written transcript of what you said")
    return recorded


def build_catalogue(cfg: ConsentSettings) -> ConsentCatalogue:
    """The consent wording for the study described by ``cfg``.

    Args:
        cfg: The ``[consent]`` section of the settings.

    Returns:
        The catalogue, with ``configured`` False while any value is still one
        of the bracketed placeholders.
    """
    lab, study, provider = cfg.laboratory_name, cfg.study_title, cfg.provider_name
    items = [
        ConsentItem(
            "P-C1",
            PARTICIPANT_REQUIRED,
            True,
            "Age",
            "I am 18 years of age or older.",
        ),
        ConsentItem(
            "P-C2",
            PARTICIPANT_REQUIRED,
            True,
            "Information",
            f"I have read the privacy notice (version {cfg.notice_version}), and I have had "
            f"the opportunity to ask questions.",
        ),
        ConsentItem(
            RECORDING_CONSENT_ID,
            PARTICIPANT_REQUIRED,
            True,
            "Explicit consent: sensor recording (Art. 9(2)(a) GDPR)",
            f"I explicitly consent to {lab} recording {_sensor_phrase(cfg)} during this VR "
            f'session, and using these recordings for the study "{study}". I understand that '
            f"this data is sensitive and may reveal information about my health.",
        ),
        ConsentItem(
            "P-C4",
            PARTICIPANT_REQUIRED,
            True,
            "Explicit consent: health and body information (Art. 9(2)(a) GDPR)",
            f"I explicitly consent to {lab} storing and using the information I give about my "
            f"body and health (such as my height, weight, eyesight, motion sickness, relevant "
            f"health conditions and how I felt after the session) for the same study.",
        ),
    ]
    if cfg.enable_av_recording:
        # Required, not optional (addendum Section 3.2): inserted into the
        # required group, ahead of the optional P-C5 block below, exactly as
        # the addendum specifies ("insert after P-C4, in the required group").
        items.append(
            ConsentItem(
                AV_RECORDING_CONSENT_ID,
                PARTICIPANT_REQUIRED,
                True,
                "Explicit consent: speech recording and transcription (Art. 9(2)(a) GDPR)",
                f"I explicitly consent to {lab} recording a video of what I see in the "
                f"headset and an audio recording of my voice while I complete the task "
                f"described to me, and converting my speech to a written transcript, for "
                f'the study "{study}". I understand that this recording and transcript '
                f"may include anything I say during the task, and that my voice can make "
                f"me personally identifiable.",
            )
        )
    if cfg.offer_provider_research:
        items.append(
            ConsentItem(
                PROVIDER_RESEARCH_CONSENT_ID,
                PARTICIPANT_OPTIONAL,
                False,
                "Optional: research use by the software provider (Art. 9(2)(a) GDPR)",
                f"I also explicitly consent to {provider}, the software provider, receiving a "
                f"copy of my recordings and answers with my name, contact details and exact date "
                f"of birth removed, and using it for {cfg.provider_research_purpose}. I understand "
                f"that eye and movement recordings can be distinctive, so this copy is still "
                f"protected as personal data. I can withdraw this consent at any time.",
            )
        )
    items += [
        ConsentItem(
            "R-C1",
            RESEARCHER,
            True,
            "Researcher confirmation",
            "I confirm that the participant personally read the information and ticked their "
            "consent choices on this device. I gave no assistance other than answering their "
            "questions.",
        ),
        ConsentItem(
            "R-C2",
            RESEARCHER,
            True,
            "Researcher confirmation",
            "I confirm that the participant appeared to understand the information, and that "
            "they were not pressured to take part.",
        ),
    ]

    short_notice = {
        "title": "Before we start: how your data is used",
        "intro": (
            "This study uses a VR headset that measures how you move and where you look. "
            "Please read this page carefully. You can ask the researcher any questions "
            "before you decide."
        ),
        "what_is_recorded": _recorded_list(cfg),
        "who_is_responsible": f"{lab}. The software is provided by {provider}.",
        "why": (
            f'For the research study "{study}": {cfg.study_purpose}. We do not use your data '
            f"to identify you, to diagnose you, or to make decisions about you."
        ),
        "how_long": f"Until {cfg.retention}, then it is deleted or made anonymous.",
        "your_choice": (
            "Taking part is voluntary. You can stop and withdraw your consent at any time, "
            "without giving a reason and without any disadvantage to you."
        ),
        "contact": cfg.laboratory_contact,
    }

    configurable = (
        cfg.laboratory_name,
        cfg.laboratory_contact,
        cfg.provider_name,
        cfg.study_title,
        cfg.study_purpose,
        cfg.retention,
    )
    configured = not any(value.startswith("[") for value in configurable)

    return ConsentCatalogue(
        text_version=CONSENT_TEXT_VERSION,
        notice_version=cfg.notice_version,
        notice_url=cfg.notice_url,
        study_id=cfg.study_id,
        study_title=study,
        laboratory_name=lab,
        provider_name=provider,
        language=cfg.wording_language,
        items=tuple(items),
        short_notice=short_notice,
        configured=configured,
    )
