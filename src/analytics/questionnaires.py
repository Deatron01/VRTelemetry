# src/analytics/questionnaires.py
"""
Scoring for the two standard post-session subjective instruments this
project has always had *columns* for (Simulator Sickness Questionnaire
subscales, NASA-TLX subscales) but never actually had a UI to collect —
every session_metadata row before this module existed carries whatever
default the INSERT statement happened to use (0.0 for the SSQ/TLX
subscales, 22.0 for perceived_temp_c), not a real measurement.

Scoring lives here (not in main.py, and not duplicated in the frontend)
so there is exactly one place that implements the published formulas,
used by the FastAPI endpoint that persists a completed questionnaire.

References:
  - Kennedy, R.S., Lane, N.E., Berbaum, K.S., & Lilienthal, M.G. (1993).
    Simulator Sickness Questionnaire: An enhanced method for quantifying
    simulator sickness. The International Journal of Aviation Psychology.
  - Hart, S.G., & Staveland, L.E. (1988). Development of NASA-TLX.
    Human Mental Workload.
  - Hart, S.G. (2006). NASA-TLX 20 years later — the commonly used
    unweighted "Raw TLX" (RTLX) simplification averaged here skips the
    15-pairwise-comparison weighting step of the full instrument; this is
    a deliberate, widely used trade-off (see Byrne, 2013) against asking a
    fatigued VR subject to do 15 pairwise judgments after every session.
"""

from typing import Dict, Any

# --- Simulator Sickness Questionnaire -----------------------------------

# Each of the 16 canonical SSQ symptoms, rated 0 (none) - 3 (severe) by the
# subject, and the subscale(s) it contributes its raw score to.
SSQ_ITEMS = [
    "general_discomfort", "fatigue", "headache", "eye_strain",
    "difficulty_focusing", "increased_salivation", "sweating", "nausea",
    "difficulty_concentrating", "fullness_of_head", "blurred_vision",
    "dizziness_eyes_open", "dizziness_eyes_closed", "vertigo",
    "stomach_awareness", "burping",
]

_SSQ_NAUSEA_SET = {
    "general_discomfort", "increased_salivation", "sweating", "nausea",
    "difficulty_concentrating", "stomach_awareness", "burping",
}
_SSQ_OCULOMOTOR_SET = {
    "general_discomfort", "fatigue", "headache", "eye_strain",
    "difficulty_focusing", "difficulty_concentrating", "blurred_vision",
}
_SSQ_DISORIENTATION_SET = {
    "difficulty_focusing", "nausea", "fullness_of_head", "blurred_vision",
    "dizziness_eyes_open", "dizziness_eyes_closed", "vertigo",
}

# Kennedy et al.'s published subscale/total multipliers.
_SSQ_N_WEIGHT = 9.54
_SSQ_O_WEIGHT = 7.58
_SSQ_D_WEIGHT = 13.92
_SSQ_TOTAL_WEIGHT = 3.74


def score_ssq(items: Dict[str, int]) -> Dict[str, Any]:
    """
    items: mapping of SSQ_ITEMS name -> severity 0-3 (missing items treated
    as 0, out-of-range values clamped, so a partially-completed form still
    produces a defensible — if incomplete — score rather than crashing).
    """
    clean = {k: max(0, min(3, int(items.get(k, 0) or 0))) for k in SSQ_ITEMS}

    n_raw = sum(v for k, v in clean.items() if k in _SSQ_NAUSEA_SET)
    o_raw = sum(v for k, v in clean.items() if k in _SSQ_OCULOMOTOR_SET)
    d_raw = sum(v for k, v in clean.items() if k in _SSQ_DISORIENTATION_SET)

    nausea = n_raw * _SSQ_N_WEIGHT
    oculomotor = o_raw * _SSQ_O_WEIGHT
    disorientation = d_raw * _SSQ_D_WEIGHT
    total_severity = (nausea + oculomotor + disorientation) * _SSQ_TOTAL_WEIGHT

    return {
        "ssq_nausea_score": round(nausea, 2),
        "ssq_oculomotor_score": round(oculomotor, 2),
        "ssq_disorientation": round(disorientation, 2),
        "ssq_total_severity": round(total_severity, 2),
        "ssq_severity_band": _ssq_band(total_severity),
        "ssq_raw_items": clean,
    }


def _ssq_band(total_severity: float) -> str:
    """
    Widely used descriptive banding for the SSQ Total Severity score (see
    e.g. Stanney, Kennedy & Drexler, 1997). These are heuristic research
    thresholds, not a clinical diagnostic cutoff — presented to the
    researcher as a guide, never as a pass/fail medical judgment.
    """
    if total_severity < 5:
        return "Negligible"
    if total_severity < 10:
        return "Minimal"
    if total_severity < 15:
        return "Significant"
    if total_severity < 20:
        return "Concerning"
    return "Severe"


# --- NASA Task Load Index ------------------------------------------------

NASA_TLX_ITEMS = [
    "mental_demand", "physical_demand", "temporal_demand",
    "performance", "effort", "frustration",
]

_NASA_TLX_LABELS = {
    "mental_demand": "Mental Demand",
    "physical_demand": "Physical Demand",
    "temporal_demand": "Temporal Demand",
    "performance": "Performance",
    "effort": "Effort",
    "frustration": "Frustration",
}


def score_nasa_tlx(items: Dict[str, float]) -> Dict[str, Any]:
    """
    items: mapping of NASA_TLX_ITEMS name -> rating 0-100. The Performance
    item is collected on the instrument's own "Perfect" (0) -> "Failure"
    (100) anchor so that, like the other five, a higher number always means
    a *worse* experience — that's what makes a plain unweighted mean
    (Raw TLX / RTLX) a meaningful single workload index without inverting
    anything first.
    """
    clean = {k: max(0.0, min(100.0, float(items.get(k, 0.0) or 0.0))) for k in NASA_TLX_ITEMS}
    rtlx = sum(clean.values()) / len(NASA_TLX_ITEMS)

    return {
        "nasa_tlx_mental": round(clean["mental_demand"], 1),
        "nasa_tlx_physical": round(clean["physical_demand"], 1),
        "nasa_tlx_temporal": round(clean["temporal_demand"], 1),
        "nasa_tlx_performance": round(clean["performance"], 1),
        "nasa_tlx_effort": round(clean["effort"], 1),
        "nasa_tlx_frustration": round(clean["frustration"], 1),
        "nasa_tlx_rtlx": round(rtlx, 1),
        "nasa_tlx_band": _tlx_band(rtlx),
    }


def _tlx_band(rtlx: float) -> str:
    """Informal workload banding used in applied HCI/VR studies (not part of the original instrument)."""
    if rtlx < 20:
        return "Low"
    if rtlx < 45:
        return "Moderate"
    if rtlx < 70:
        return "High"
    return "Very High"


_THERMAL_COMFORT_SCALE = [
    "cold", "cool", "slightly_cool", "neutral",
    "slightly_warm", "warm", "hot",
]


def is_valid_thermal_comfort(value: str) -> bool:
    return value in _THERMAL_COMFORT_SCALE
