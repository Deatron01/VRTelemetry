# plugins/medical-plugin-01/ssq_nasa_tlx.py
"""SSQ and NASA-TLX scoring -- relocated, unmodified, from
`src/analytics/questionnaires.py` in the Core Hub.

This is a straight copy of the scoring functions, not a reimplementation:
the formulas, weights and bands below must stay byte-identical to whatever
the Core Hub still uses (see the plan doc's note on `questionnaires.py`
staying in place there too, at least until a decision is made to route
scoring exclusively through this plugin). If the Core Hub's copy changes,
copy the change here too, or the two will silently disagree about a
participant's score depending on which path happened to run.

References:
  - Kennedy, R.S., Lane, N.E., Berbaum, K.S., & Lilienthal, M.G. (1993).
    Simulator Sickness Questionnaire: An enhanced method for quantifying
    simulator sickness. The International Journal of Aviation Psychology.
  - Hart, S.G., & Staveland, L.E. (1988). Development of NASA-TLX.
    Human Mental Workload.
  - Hart, S.G. (2006). NASA-TLX 20 years later -- the commonly used
    unweighted "Raw TLX" (RTLX) simplification averaged here skips the
    15-pairwise-comparison weighting step of the full instrument; this is
    a deliberate, widely used trade-off (see Byrne, 2013).
"""

from typing import Any

# --- Simulator Sickness Questionnaire -----------------------------------

SSQ_ITEMS = [
    "general_discomfort",
    "fatigue",
    "headache",
    "eye_strain",
    "difficulty_focusing",
    "increased_salivation",
    "sweating",
    "nausea",
    "difficulty_concentrating",
    "fullness_of_head",
    "blurred_vision",
    "dizziness_eyes_open",
    "dizziness_eyes_closed",
    "vertigo",
    "stomach_awareness",
    "burping",
]

_SSQ_NAUSEA_SET = {
    "general_discomfort",
    "increased_salivation",
    "sweating",
    "nausea",
    "difficulty_concentrating",
    "stomach_awareness",
    "burping",
}
_SSQ_OCULOMOTOR_SET = {
    "general_discomfort",
    "fatigue",
    "headache",
    "eye_strain",
    "difficulty_focusing",
    "difficulty_concentrating",
    "blurred_vision",
}
_SSQ_DISORIENTATION_SET = {
    "difficulty_focusing",
    "nausea",
    "fullness_of_head",
    "blurred_vision",
    "dizziness_eyes_open",
    "dizziness_eyes_closed",
    "vertigo",
}

_SSQ_N_WEIGHT = 9.54
_SSQ_O_WEIGHT = 7.58
_SSQ_D_WEIGHT = 13.92
_SSQ_TOTAL_WEIGHT = 3.74


def score_ssq(items: dict[str, int]) -> dict[str, Any]:
    """items: mapping of SSQ_ITEMS name -> severity 0-3 (missing items treated
    as 0, out-of-range values clamped)."""
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
    """Heuristic research thresholds (Stanney, Kennedy & Drexler, 1997), not
    a clinical diagnostic cutoff."""
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
    "mental_demand",
    "physical_demand",
    "temporal_demand",
    "performance",
    "effort",
    "frustration",
]


def score_nasa_tlx(items: dict[str, float]) -> dict[str, Any]:
    """items: mapping of NASA_TLX_ITEMS name -> rating 0-100, Performance on
    its own "Perfect" (0) -> "Failure" (100) anchor so a plain unweighted
    mean (Raw TLX / RTLX) is meaningful without inverting anything first."""
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
