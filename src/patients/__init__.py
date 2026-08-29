# src/patients/__init__.py

"""
Patient Registry Layer.
Durable subject/patient identity records, decoupled from per-recording
session_metadata. See PatientManager for the GDPR consent lifecycle.
"""

from .patient_manager import PatientManager, CURRENT_CONSENT_VERSION

__all__ = ["PatientManager", "CURRENT_CONSENT_VERSION"]