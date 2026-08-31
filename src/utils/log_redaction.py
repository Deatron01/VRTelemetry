# src/utils/log_redaction.py
"""Redaction of personal data from log records.

This module exists because of a specific defect (VRT-3): the central server's
patient-upload route logged the entire inbound payload -- display name, date of
birth, declared health conditions -- into a plaintext, unrotated log whenever a
required field was missing. A validation failure should never cost a research
subject their confidentiality.

The primary fix is at the call sites: log field *names*, never field values.
This filter is the second line of defence, for the call site nobody has written
yet. :func:`src.utils.logger.setup_logging` attaches it to every handler --
console, engine log, and the per-session capture handler alike.

It is attached per *handler* rather than to the root logger on purpose. A filter
on a ``Logger`` runs only for records logged through that logger directly:
``Logger.handle()`` applies its own filters and then calls ``callHandlers()``,
which walks ancestor *handlers* but never ancestor *filters*. Every call site in
this codebase uses the ``"VRTelemetry"`` child logger, so a root-logger filter
would silently never run.

Design notes:

* Redaction is **key-driven**, not value-driven. Matching on values would mean
  guessing what a name or a diagnosis looks like, which is both unreliable and
  locale-dependent. Matching on keys is exact, and the keys are ours.
* The filter mutates a *copy* of the record's structures, never the caller's
  objects. A log call must not change program behaviour.
* Redaction is applied to ``record.args`` and to already-formatted
  ``record.msg`` strings, since both routes reach the handler.
* Unknown keys are left alone deliberately. A denylist that silently swallows
  unrelated fields makes logs useless and pushes people to bypass logging
  entirely.

Adding a field: put it in :data:`SENSITIVE_KEYS`. The test suite asserts that
every field on the patient record model is either listed here or explicitly
recorded as non-personal.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

#: Placeholder substituted for any redacted value. Deliberately visible in logs:
#: an operator reading a log needs to know that a field was present and withheld,
#: not that it was absent.
REDACTED: Final[str] = "[REDACTED]"

#: Field names whose *values* must never appear in a log record.
#:
#: Sourced from ``PatientManager.HEALTH_PROFILE_FIELDS`` and the patient/session
#: table columns that carry directly or indirectly identifying data. Compared
#: case-insensitively.
SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        # Direct identifiers
        "display_name",
        "patient_display_name",
        "external_ref",
        "date_of_birth",
        "notes",
        # Special-category health data (GDPR Art. 9)
        "biological_sex",
        "relevant_health_conditions",
        "vision_correction",
        "vision_impairment",
        "motion_sickness_susceptibility",
        "height_cm",
        "weight_kg",
        "age_years",
        "subject_age",
        "subject_height_cm",
        "subject_weight_kg",
        "subject_biological_sex",
        # Credentials and bearer material
        "password",
        "password_hash",
        "password_salt",
        "session_token",
        "license_key",
    }
)

#: Matches ``key: value`` / ``key=value`` / ``'key': 'value'`` occurrences of a
#: sensitive key inside an already-formatted message string. Built once at import.
_INLINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<key>['\"]?\b(?:" + "|".join(sorted(SENSITIVE_KEYS)) + r")\b['\"]?\s*[:=]\s*)"
    r"(?P<value>'[^']*'|\"[^\"]*\"|[^,}\)\]\s][^,}\)\]]*)",
    re.IGNORECASE,
)


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a copy of ``value`` with sensitive fields replaced.

    Recurses through dicts, lists, tuples and sets. Scalars pass through
    untouched -- a bare string carries no key to match against, and guessing
    from its shape is exactly the unreliable value-matching this module avoids.

    Args:
        value: Any structure destined for a log record.
        _depth: Internal recursion guard. Structures nested more than 12 deep
            are returned as a placeholder rather than walked; nothing this
            application logs is legitimately that deep, and a cyclic structure
            must not hang the logging call.

    Returns:
        A new structure of the same shape. The input is never mutated.
    """
    if _depth > 12:
        return "[REDACTION_DEPTH_EXCEEDED]"

    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and key.lower() in SENSITIVE_KEYS
                else redact(item, _depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return type(value)(redact(item, _depth + 1) for item in value)
    return value


def redact_text(text: str) -> str:
    """Redact ``key=value`` pairs for sensitive keys inside a formatted string.

    Catches the common case of a caller interpolating a payload into an f-string
    before the logging machinery ever sees it as structured data -- which is
    precisely how the original defect was written.

    Args:
        text: An already-formatted log message.

    Returns:
        The message with sensitive values replaced by :data:`REDACTED`.
    """
    return _INLINE_PATTERN.sub(lambda m: f"{m.group('key')}{REDACTED}", text)


class PersonalDataFilter(logging.Filter):
    """Logging filter that strips personal data from every record it sees.

    Attached to each handler by :func:`src.utils.logger.setup_logging` -- see the
    module docstring for why not to the root logger. Never drops a
    record -- :meth:`filter` always returns ``True``; it only rewrites content.
    Losing the fact that an error occurred would be a worse outcome than logging
    it with fields withheld.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite ``record`` in place, then admit it.

        Args:
            record: The record about to be handed to the handlers.

        Returns:
            Always ``True``.
        """
        if record.args:
            record.args = redact(record.args)

        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        elif isinstance(record.msg, (dict, list, tuple, set)):
            record.msg = redact(record.msg)

        return True
