# src/interfaces/api/routers/questionnaires.py
"""Post-session SSQ / NASA-TLX / thermal-comfort scoring.

Moved from src/main.py. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from src.analytics.questionnaires import (
    NASA_TLX_ITEMS,
    SSQ_ITEMS,
    is_valid_thermal_comfort,
    score_nasa_tlx,
    score_ssq,
)
from src.interfaces.api import dependencies as deps
from src.interfaces.api.schemas.questionnaires import QuestionnaireSubmission
from src.utils.logger import logger

router = APIRouter(tags=["questionnaires"])


@router.post("/api/sessions/{session_id}/questionnaire")
def submit_questionnaire(session_id: str, submission: QuestionnaireSubmission):
    """
    Scores and persists the post-session SSQ + NASA-TLX + thermal-comfort
    questionnaire for an already-recorded session, then best-effort re-syncs
    the updated metadata to the central server if this session was already
    uploaded (see SessionUploader.update_remote_metadata).
    """

    row = deps.db_manager.get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    # A session linked to a patient whose GDPR consent has since been withdrawn
    # or erased must not accept new special-category health data either —
    # same rule as starting a new recording for that patient.
    patient_id = row.get("patient_id")
    if patient_id:
        patient = deps.patients.get_patient(patient_id)
        if patient and (patient["is_anonymized"] or not patient["gdpr_consent_given"]):
            raise HTTPException(
                status_code=403,
                detail="This session's patient record has withdrawn or erased GDPR consent; "
                "new subjective/health data cannot be recorded against it.",
            )

    payload = submission.dict()
    ssq_scores = score_ssq({k: payload.get(k) for k in SSQ_ITEMS})
    tlx_scores = score_nasa_tlx({k: payload.get(k) for k in NASA_TLX_ITEMS})

    fields: dict[str, Any] = {
        "ssq_nausea_score": ssq_scores["ssq_nausea_score"],
        "ssq_oculomotor_score": ssq_scores["ssq_oculomotor_score"],
        "ssq_disorientation": ssq_scores["ssq_disorientation"],
        "ssq_total_severity": ssq_scores["ssq_total_severity"],
        "ssq_severity_band": ssq_scores["ssq_severity_band"],
        "ssq_raw_items_json": json.dumps(ssq_scores["ssq_raw_items"]),
        "nasa_tlx_mental": tlx_scores["nasa_tlx_mental"],
        "nasa_tlx_physical": tlx_scores["nasa_tlx_physical"],
        "nasa_tlx_temporal": tlx_scores["nasa_tlx_temporal"],
        "nasa_tlx_performance": tlx_scores["nasa_tlx_performance"],
        "nasa_tlx_effort": tlx_scores["nasa_tlx_effort"],
        "nasa_tlx_frustration": tlx_scores["nasa_tlx_frustration"],
        "nasa_tlx_rtlx": tlx_scores["nasa_tlx_rtlx"],
        "nasa_tlx_band": tlx_scores["nasa_tlx_band"],
        "nasa_tlx_raw_items_json": json.dumps({k: payload.get(k) for k in NASA_TLX_ITEMS}),
        "questionnaire_completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if submission.thermal_comfort and is_valid_thermal_comfort(submission.thermal_comfort):
        fields["thermal_comfort"] = submission.thermal_comfort
    if submission.perceived_temp_c is not None:
        fields["perceived_temp_c"] = submission.perceived_temp_c
    if submission.session_rating is not None:
        fields["session_rating"] = submission.session_rating

    saved = deps.db_manager.save_subjective_questionnaire(session_id, fields)
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to persist questionnaire")

    # Best-effort push of the refreshed row to the central server. Never blocks
    # or fails the response — the local record is authoritative regardless.
    updated_row = deps.db_manager.get_session_row(session_id)
    try:
        deps.session_uploader.update_remote_metadata(session_id, updated_row)
    except Exception as e:
        logger.info(f"Questionnaire saved locally; central re-sync skipped: {e}")

    return {"ok": True, "ssq": ssq_scores, "nasa_tlx": tlx_scores}
