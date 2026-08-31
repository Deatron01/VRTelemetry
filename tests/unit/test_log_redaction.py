"""Tests for personal-data redaction in log output (VRT-3).

The defect these guard against was concrete: ``/data/upload-patient`` logged the
entire inbound payload -- display name, date of birth, declared health
conditions -- whenever a required field was missing. These tests assert on the
*rendered log output*, not on the filter's internals, because the only property
that matters is whether a subject's data can end up in a log file.
"""

from __future__ import annotations

import io
import logging

import pytest

from src.utils.log_redaction import (
    REDACTED,
    PersonalDataFilter,
    redact,
    redact_text,
)

PATIENT_PAYLOAD = {
    "activation_id": "act-123",
    "license_id": "lic-456",
    "patient": {
        "patient_id": "pat-789",
        "display_name": "Test Subject",
        "date_of_birth": "1994-03-02",
        "relevant_health_conditions": "epilepsy, migraine with aura",
        "height_cm": 178.0,
        "gdpr_consent_given": True,
    },
}

#: Every value that must never reach a log sink, drawn from the payload above.
FORBIDDEN_SUBSTRINGS = (
    "Test Subject",
    "1994-03-02",
    "epilepsy",
    "migraine with aura",
)


@pytest.fixture
def captured_log() -> tuple[logging.Logger, io.StringIO]:
    """A child logger writing to an in-memory handler with the filter installed.

    Mirrors the real wiring: the filter is attached to the *handler*, and
    records are emitted on a child logger, because a filter on the root logger
    would never run for child-logger records.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(PersonalDataFilter())

    logger = logging.getLogger("VRTelemetry.test_redaction")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    yield logger, stream

    logger.handlers.clear()


def test_fstring_interpolated_payload_is_redacted(captured_log) -> None:
    """The exact defect: a payload interpolated into an f-string before logging."""
    logger, stream = captured_log

    logger.error(f"Sync rejected. Payload received: {PATIENT_PAYLOAD}")

    output = stream.getvalue()
    for secret in FORBIDDEN_SUBSTRINGS:
        assert secret not in output, f"{secret!r} leaked into log output"
    # The record must still be useful: the non-personal context survives.
    assert "Sync rejected" in output
    assert "act-123" in output


def test_lazy_logging_args_are_redacted(captured_log) -> None:
    """Structured %-style args are redacted before formatting."""
    logger, stream = captured_log

    logger.error("Sync rejected. Payload: %s", PATIENT_PAYLOAD)

    output = stream.getvalue()
    for secret in FORBIDDEN_SUBSTRINGS:
        assert secret not in output
    assert REDACTED in output


def test_filter_never_drops_a_record(captured_log) -> None:
    """Redaction must not cost us the fact that something failed."""
    logger, stream = captured_log

    logger.error("Sync rejected for patient display_name='Test Subject'")

    assert "Sync rejected" in stream.getvalue()


def test_redact_does_not_mutate_the_caller_s_object() -> None:
    """A log call must not change program state."""
    original = {"display_name": "Test Subject", "patient_id": "pat-789"}
    snapshot = dict(original)

    result = redact(original)

    assert original == snapshot, "redact() mutated its input"
    assert result["display_name"] == REDACTED
    assert result["patient_id"] == "pat-789"


def test_non_personal_fields_survive() -> None:
    """A denylist that swallows everything makes logs useless and gets bypassed."""
    result = redact(
        {
            "session_id": "20260527_133428",
            "total_frames": 41207,
            "patient_id": "pat-789",
            "display_name": "Test Subject",
        }
    )

    assert result["session_id"] == "20260527_133428"
    assert result["total_frames"] == 41207
    assert result["patient_id"] == "pat-789"
    assert result["display_name"] == REDACTED


def test_nested_structures_are_walked() -> None:
    """Sensitive fields nested inside lists and dicts are still caught."""
    result = redact({"patients": [{"display_name": "A"}, {"display_name": "B"}]})

    assert [p["display_name"] for p in result["patients"]] == [REDACTED, REDACTED]


def test_cyclic_structure_does_not_hang() -> None:
    """A cyclic payload must not turn a log call into an infinite loop."""
    node: dict = {"display_name": "Test Subject"}
    node["self"] = node

    result = redact(node)

    assert result["display_name"] == REDACTED


@pytest.mark.parametrize(
    "text",
    [
        "display_name: Test Subject",
        "display_name='Test Subject'",
        '{"display_name": "Test Subject"}',
        "DISPLAY_NAME = Test Subject",
    ],
)
def test_inline_key_value_forms_are_redacted(text: str) -> None:
    """The common textual spellings a developer might produce by hand."""
    assert "Test Subject" not in redact_text(text)


def test_credentials_are_redacted() -> None:
    """Bearer material is treated the same as personal data."""
    result = redact({"password": "hunter2", "session_token": "abc123", "license_key": "AAAA-BBBB"})

    assert set(result.values()) == {REDACTED}
