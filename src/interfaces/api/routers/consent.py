# src/interfaces/api/routers/consent.py
"""The consent wording, and finding a participant by their withdrawal code (GDPR-09)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.interfaces.api.dependencies import ConsentsDep

router = APIRouter(tags=["consent"])


class WithdrawalCodeLookup(BaseModel):
    code: str


@router.get("/api/consent/texts")
def get_consent_texts(consents: ConsentsDep) -> dict[str, Any]:
    """The exact wording the consent screen must display, with a hash per item.

    The desktop app renders these texts verbatim and returns each hash with the
    participant's answers. ``configured`` is false while the study details in
    ``[consent]`` are still placeholders; the app shows that as a warning,
    because consent to "[Laboratory Name]" informs nobody of anything.
    """
    return consents.catalogue().as_dict()


@router.post("/api/consent/withdrawal-code")
def find_by_withdrawal_code(payload: WithdrawalCodeLookup, consents: ConsentsDep) -> dict[str, Any]:
    """Which participant a withdrawal code belongs to.

    For the participant who contacts the laboratory after the session, quoting
    the code from their receipt: it identifies their record without the
    laboratory having kept their contact details (Art. 11 GDPR).
    """
    record = consents.find_by_withdrawal_code(payload.code)
    if record is None:
        raise HTTPException(status_code=404, detail="No consent matches that withdrawal code.")
    return {
        "patient_id": record["patient_id"],
        "consent_id": record["consent_id"],
        "study_title": record["study_title"],
        "given_at_utc": record["given_at_utc"],
    }
