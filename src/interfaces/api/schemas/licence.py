# src/interfaces/api/schemas/licence.py
"""Licence activation model."""

from __future__ import annotations

import platform

from pydantic import BaseModel


class LicenseActivateRequest(BaseModel):
    license_key: str
    machine_label: str = platform.node()
