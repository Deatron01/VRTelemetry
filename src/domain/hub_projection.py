# src/domain/hub_projection.py
"""What of a participant is allowed to leave the laboratory (GDPR-11).

The workstation is where a laboratory -- the controller -- keeps its study
data, including the things it needs to recognise a participant: a name, a
hospital or study reference, a date of birth, free-text notes. The hub is a
shared service. Before this module, every one of those fields travelled to it:
``PatientSyncClient`` posted the whole ``patients`` row, the hub filed it in
``synced_patients`` with a ``raw_json`` copy, the admin dashboard showed the
name, the date of birth and the free-text health notes, and the recording route
set ``subject_id`` to the participant's display name, so the name was also
stamped on every uploaded session.

That contradicts both the data-minimisation principle (Art. 5(1)(c) GDPR) and
the product's own goal: the provider wants de-identified access to study data,
and a hub full of names is the opposite.

So this is an **allowlist** for patients and a **denylist** for session
metadata, applied in three places:

* the workstation, before anything is sent *or queued* for sending
  (``PatientSyncClient``, ``SessionUploader``);
* the hub, on receipt (``CentralDataManager``), so an old or modified client
  cannot put identifiers back;
* the hub's schema initialisation, once, over rows written before this existed.

An allowlist for patients because the ``patients`` table grows: a column added
next month must not leave the building until someone decides it may. Session
metadata is a free-form nested document assembled from half a dozen sources,
where an allowlist would silently drop the telemetry context the hub exists to
hold, so there the known identifiers are removed by name at any depth.

The projection is pure: no I/O, no clock of its own (``today`` is passed in).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

#: Fields of a patient record the hub may receive. Everything else is dropped.
#:
#: Deliberately absent: ``display_name``, ``external_ref``, ``date_of_birth``
#: (replaced by ``age_years``), ``notes``, and the two free-text health fields
#: ``vision_impairment`` and ``relevant_health_conditions``. Free text is where
#: names, diagnoses and hospital numbers end up regardless of the label on the
#: field, so it stays with the controller.
HUB_PATIENT_FIELDS: tuple[str, ...] = (
    "patient_id",
    "biological_sex",
    "age_years",
    "height_cm",
    "weight_kg",
    "dominant_hand",
    "vr_experience_level",
    "vr_experience_hours_estimate",
    "gaming_experience_hours_per_week",
    "vision_correction",
    "motion_sickness_susceptibility",
    "gdpr_consent_given",
    "gdpr_consent_version",
    "gdpr_consent_timestamp",
    "gdpr_consent_withdrawn_at",
    "is_anonymized",
    "created_at",
    "updated_at",
)

#: Keys removed from session metadata, at any depth, before it leaves the
#: workstation. The participant identifiers above, plus two that identify the
#: *researcher*: the workstation's host name and operating-system user name,
#: which the system profile collects and which are very often a person's name.
HUB_EXCLUDED_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "display_name",
        "external_ref",
        "date_of_birth",
        "notes",
        "vision_impairment",
        "relevant_health_conditions",
        "hostname",
        "os_user",
    }
)

#: Metadata values that are themselves JSON documents (``session_metadata``
#: keeps a ``raw_json`` copy of everything the engine knew). They are parsed,
#: projected and re-serialised, because a denylist that stops at the string
#: boundary would let the whole unprojected document through inside one field.
_EMBEDDED_JSON_KEYS: frozenset[str] = frozenset({"raw_json", "metadata_json"})


def age_from_date_of_birth(date_of_birth: str | None, today: date) -> int | None:
    """Whole years between ``date_of_birth`` and ``today``, or None if unknown.

    Calendar arithmetic between two dates, not an instant: comparing a birth
    date against a UTC timestamp is off by a day around a birthday depending on
    where the machine is standing.

    Args:
        date_of_birth: ``YYYY-MM-DD`` or ``YYYY/MM/DD``; anything longer is
            truncated to its first ten characters.
        today: The reference date, passed in so the function stays pure.

    Returns:
        The age, or None when the date is missing, unparseable or implausible.
    """
    if not date_of_birth:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            born = datetime.strptime(date_of_birth[:10], fmt).date()  # noqa: DTZ007 - a date, not an instant
        except ValueError:
            continue
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return age if 0 <= age <= 130 else None
    return None


def project_patient_for_hub(patient: Mapping[str, Any], today: date) -> dict[str, Any]:
    """The subset of a patient record that may be sent to the hub.

    ``age_years`` is derived from ``date_of_birth`` when one is recorded, so the
    hub keeps the covariate it needs without receiving the date itself. A
    record without a date of birth keeps whatever ``age_years`` it has.

    Args:
        patient: A row from the workstation's ``patients`` table, or a payload
            received by the hub.
        today: Reference date for the age calculation.

    Returns:
        A new dict containing only :data:`HUB_PATIENT_FIELDS` that are present.
    """
    projected = {key: patient[key] for key in HUB_PATIENT_FIELDS if key in patient}
    derived_age = age_from_date_of_birth(patient.get("date_of_birth"), today)
    if derived_age is not None:
        projected["age_years"] = derived_age
    return projected


def project_session_metadata_for_hub(metadata: Any) -> Any:
    """Session metadata with every key in :data:`HUB_EXCLUDED_METADATA_KEYS` removed.

    Recurses through dicts and lists, and through the string values of
    ``raw_json`` / ``metadata_json``. A value in one of those keys that is not
    valid JSON is dropped rather than passed through: it cannot be inspected,
    so it cannot be shown to be safe.

    Args:
        metadata: Any JSON-shaped value; normally a dict.

    Returns:
        A projected copy. The input is not modified.
    """
    if isinstance(metadata, Mapping):
        result: dict[str, Any] = {}
        for key, value in metadata.items():
            if key in HUB_EXCLUDED_METADATA_KEYS:
                continue
            if key in _EMBEDDED_JSON_KEYS and isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except ValueError:
                    continue
                result[key] = json.dumps(project_session_metadata_for_hub(parsed))
                continue
            result[key] = project_session_metadata_for_hub(value)
        return result
    if isinstance(metadata, list):
        return [project_session_metadata_for_hub(item) for item in metadata]
    return metadata
