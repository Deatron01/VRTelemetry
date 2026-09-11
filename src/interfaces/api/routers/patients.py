# src/interfaces/api/routers/patients.py
"""Patient registry and the GDPR consent lifecycle.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12.

GDPR-09 changed what "consent" means here. Creating a patient used to require a
boolean the researcher ticked. It now requires the participant's own answers
from the consent screen, validated against the exact wording served by
``GET /api/consent/texts`` and stored in the append-only consent register. The
patient row's ``gdpr_consent_*`` columns remain, as a summary of that register.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from src.application.consent import ConsentValidationError, WithdrawalScope
from src.core.exceptions import GDPRConsentError
from src.interfaces.api.dependencies import (
    ConsentsDep,
    LocalCacheDep,
    PatientsDep,
    PatientUploaderDep,
    SessionsDep,
)
from src.interfaces.api.schemas.patients import (
    ConsentSubmissionModel,
    PatientCreateRequest,
    PatientUpdateRequest,
    WithdrawalRequest,
)

router = APIRouter(tags=["patients"])


def _supervision(local_cache: Any) -> dict[str, str | None]:
    """Who supervised the consent, and on which workstation -- for the record.

    Best effort: a workstation that is not logged in or not activated still
    records consent, it just records less about the circumstances.
    """
    session = local_cache.get_session() or {}
    state = local_cache.get_state() or {}
    return {
        "researcher_user": session.get("email"),
        "workstation": state.get("machine_label") or state.get("activation_id"),
    }


def _public_consent(record: dict[str, Any]) -> dict[str, Any]:
    """What the client is told about a consent it just recorded.

    The withdrawal code is included -- this is the only response that ever
    carries it -- and its hash is not.
    """
    return {
        "consent_id": record["consent_id"],
        "study_id": record["study_id"],
        "study_title": record["study_title"],
        "text_version": record["text_version"],
        "choices": record["choices"],
        "given_at_utc": record["given_at_utc"],
        "withdrawal_code": record.get("withdrawal_code"),
    }


@router.get("/api/patients")
def list_patients(patients: PatientsDep, include_anonymized: bool = False):
    return patients.list_patients(include_anonymized=include_anonymized)


@router.post("/api/patients")
def create_patient(
    payload: PatientCreateRequest,
    patients: PatientsDep,
    consents: ConsentsDep,
    patient_uploader: PatientUploaderDep,
    local_cache: LocalCacheDep,
):
    if payload.consent is None:
        raise HTTPException(
            status_code=403,
            detail="A patient record requires the participant's own consent from the consent "
            "screen (GDPR Art. 9(2)(a)). Nothing has been stored.",
        )
    submission = payload.consent.to_domain()
    try:
        # Validated before anything is written: a refused consent must leave no
        # patient row behind, not even an empty one.
        catalogue = consents.validate(submission)
    except ConsentValidationError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    try:
        patient = patients.create_patient(
            display_name=payload.display_name,
            gdpr_consent_given=True,
            gdpr_consent_version=catalogue.text_version,
            external_ref=payload.external_ref,
            date_of_birth=payload.date_of_birth,
            biological_sex=payload.biological_sex,
            notes=payload.notes,
            age_years=payload.age_years,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
            dominant_hand=payload.dominant_hand,
            vr_experience_level=payload.vr_experience_level,
            vr_experience_hours_estimate=payload.vr_experience_hours_estimate,
            gaming_experience_hours_per_week=payload.gaming_experience_hours_per_week,
            vision_correction=payload.vision_correction,
            vision_impairment=payload.vision_impairment,
            motion_sickness_susceptibility=payload.motion_sickness_susceptibility,
            relevant_health_conditions=payload.relevant_health_conditions,
        )
    except GDPRConsentError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        record = consents.give(patient["patient_id"], submission, **_supervision(local_cache))
    except ConsentValidationError as e:
        # The wording changed between validate() and give(). Remove the row
        # that was created for a consent that was then not recorded.
        patients.delete_patient(patient["patient_id"], hard_delete=True)
        raise HTTPException(status_code=403, detail=str(e)) from e

    stored = (
        patients.mark_consent_given(
            patient["patient_id"], record["text_version"], record["given_at_utc"]
        )
        or patient
    )
    patient_uploader.sync_patient(dict(stored))
    return {**stored, "consent": _public_consent(record)}


@router.post("/api/patients/{patient_id}/consents")
def give_consent(
    patient_id: str,
    payload: ConsentSubmissionModel,
    patients: PatientsDep,
    consents: ConsentsDep,
    patient_uploader: PatientUploaderDep,
    local_cache: LocalCacheDep,
):
    """Record a new consent for an existing participant.

    For a new study, new wording, or a participant who withdrew and has now
    agreed again. The earlier consents and their withdrawals stay on record.
    """
    patient = patients.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient["is_anonymized"]:
        raise HTTPException(status_code=409, detail="This patient's data has been erased.")
    try:
        record = consents.give(patient_id, payload.to_domain(), **_supervision(local_cache))
    except ConsentValidationError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    updated = patients.mark_consent_given(
        patient_id, record["text_version"], record["given_at_utc"]
    )
    if updated:
        patient_uploader.sync_patient(dict(updated))
    return _public_consent(record)


@router.get("/api/patients/{patient_id}/consents")
def list_consents(patient_id: str, patients: PatientsDep, consents: ConsentsDep):
    """Every consent and consent event for one participant (Art. 7(1) evidence)."""
    if not patients.get_patient(patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    return consents.history(patient_id)


@router.put("/api/patients/{patient_id}")
def update_patient(
    patient_id: str,
    payload: PatientUpdateRequest,
    patients: PatientsDep,
    patient_uploader: PatientUploaderDep,
):
    try:
        updated = patients.update_patient(
            patient_id, {k: v for k, v in payload.dict().items() if v is not None}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient_uploader.sync_patient(updated)
    return updated


@router.post("/api/patients/{patient_id}/withdraw-consent")
def withdraw_patient_consent(
    patient_id: str,
    patients: PatientsDep,
    consents: ConsentsDep,
    patient_uploader: PatientUploaderDep,
    payload: WithdrawalRequest | None = None,
):
    """Withdraw consent, with the scope the participant chose (Art. 7(3) GDPR).

    An empty body means ``FUTURE_ONLY``, which is what this route always did.
    """
    scope = payload.scope if payload else WithdrawalScope.FUTURE_ONLY
    if not patients.get_patient(patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    if scope is WithdrawalScope.ALL_DELETE:
        raise HTTPException(
            status_code=501, detail="Withdrawal with erasure is not available in this build."
        )

    affected = consents.withdraw(patient_id, scope)
    if scope is WithdrawalScope.PROVIDER_RESEARCH_ONLY:
        updated = patients.get_patient(patient_id)
    else:
        updated = patients.withdraw_consent(patient_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient_uploader.sync_patient(dict(updated))
    return {**updated, "withdrawal": {"scope": scope.value, "consents": affected}}


@router.delete("/api/patients/{patient_id}")
def delete_patient(
    patient_id: str,
    patients: PatientsDep,
    patient_uploader: PatientUploaderDep,
    hard_delete: bool = False,
):
    ok = patients.delete_patient(patient_id, hard_delete=hard_delete)
    if not ok:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not hard_delete:
        # Push the now-anonymized record so central's copy reflects the erasure
        # instead of silently keeping the pre-erasure PII forever.
        anonymized = patients.get_patient(patient_id)
        if anonymized:
            patient_uploader.sync_patient(anonymized)
    return {"ok": True}


@router.get("/api/patients/{patient_id}/sessions")
def get_patient_sessions(patient_id: str, patients: PatientsDep, sessions: SessionsDep):
    patient = patients.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return {
        "patient": patient,
        "sessions": sessions.list_for_patient(patient_id),
    }
