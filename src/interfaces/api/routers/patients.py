# src/interfaces/api/routers/patients.py
"""Patient registry and the GDPR consent lifecycle.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.core.exceptions import GDPRConsentError
from src.interfaces.api.dependencies import PatientsDep, PatientUploaderDep, SessionsDep
from src.interfaces.api.schemas.patients import PatientCreateRequest, PatientUpdateRequest

router = APIRouter(tags=["patients"])


@router.get("/api/patients")
def list_patients(patients: PatientsDep, include_anonymized: bool = False):
    return patients.list_patients(include_anonymized=include_anonymized)


@router.post("/api/patients")
def create_patient(
    payload: PatientCreateRequest,
    patients: PatientsDep,
    patient_uploader: PatientUploaderDep,
):
    try:
        patient = patients.create_patient(
            display_name=payload.display_name,
            gdpr_consent_given=payload.gdpr_consent_given,
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
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    patient_uploader.sync_patient(patient)
    return patient


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
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient_uploader.sync_patient(updated)
    return updated


@router.post("/api/patients/{patient_id}/withdraw-consent")
def withdraw_patient_consent(
    patient_id: str,
    patients: PatientsDep,
    patient_uploader: PatientUploaderDep,
):
    updated = patients.withdraw_consent(patient_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient_uploader.sync_patient(updated)
    return updated


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
