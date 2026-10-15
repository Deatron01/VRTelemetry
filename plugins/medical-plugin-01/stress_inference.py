# plugins/medical-plugin-01/stress_inference.py
"""Deliberately not implemented.

The Core Hub's own A/V-recording work already hit this: a stress/arousal
score derived from biometrics or speech is plausibly a prohibited
emotion-recognition system under EU AI Act Art. 5(1)(f) in a
workplace/training-adjacent context. `src/av_recording/stress_score.py`'s
`StressScorer.score()` raises `StressScoringNotImplementedError`
unconditionally for exactly this reason, pending a specific counsel opinion.

This module exists so Plugin 01's biometric summary has an explicit, honest
"not available" slot instead of silently omitting the question -- never so a
placeholder number ships in its place.

Do not implement `summarize_session` to return a score without first
resolving that legal question, and keep it in step with
`src/av_recording/stress_score.py` if that module's status changes.
"""

from __future__ import annotations

from typing import Any


class StressInferenceUnavailableError(RuntimeError):
    """Raised unconditionally by `summarize_session`. See module docstring."""


def summarize_session(_biometric_summary: dict[str, Any]) -> dict[str, Any]:
    """Never returns. `_biometric_summary` is unused -- kept in the signature
    so a caller doesn't have to special-case this function once it's ever
    implemented for real; see the module docstring for why that isn't now."""
    raise StressInferenceUnavailableError(
        "Stress/arousal inference is not implemented pending a legal opinion on EU AI Act "
        "Art. 5(1)(f). Do not add a score "
        "here without resolving that first; mirror src/av_recording/stress_score.py's status."
    )
