# tests/unit/test_clock.py
"""Time, made explicit (VRT-21).

The backlog described this ticket as "16 naive ``datetime.utcnow()`` compared
against stored ISO-8601 strings for licence expiry -- a real correctness bug the
moment his hub and his workstations are not in the same timezone." That
description is wrong, and the tests below are written against what was actually
true instead: ``utcnow()`` is UTC wherever it runs, every stored value it was
compared against is also UTC, and naive-vs-naive is timezone-independent. Those
comparisons were correct on any machine.

What was wrong is that the convention was never stated, so:

* a value with a zone and a value without one already coexist in this database
  and cannot be compared -- one ``TypeError`` away, inside a licence check;
* a ``None`` expiry raised instead of meaning "no expiry";
* the wire format carries no zone, so JavaScript reads it as local time (see
  ``asUtc`` in the hub's admin UI, and the test for it below);
* ``datetime.utcnow()`` is deprecated from Python 3.12, which this project
  claims to support.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.utils.clock import as_stored, is_expired, parse_utc, utc_now, utc_now_iso, utc_today

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "stored",
    [
        "2026-09-01T08:00:00",  # datetime.utcnow().isoformat()
        "2026-09-01T08:00:00.000000",  # ... with microseconds
        "2026-09-01 08:00:00",  # SQLite CURRENT_TIMESTAMP
        "2026-09-01T08:00:00+00:00",  # datetime.now(timezone.utc)
        "2026-09-01T08:00:00Z",  # what the wire will carry once it is explicit
    ],
)
def test_every_shape_this_repository_has_written_reads_back_as_the_same_instant(
    stored: str,
) -> None:
    """Five formats, four writers, one instant.

    The 'Z' form is accepted before anything emits it, so making the wire format
    explicit later needs no coordination between the hub and the workstations
    that read it.
    """
    parsed = parse_utc(stored)

    assert parsed == datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    assert parsed.tzinfo is not None, "a parsed timestamp must know its zone"


def test_a_stored_value_without_a_zone_is_taken_as_utc() -> None:
    """Stated here, rather than assumed at fourteen call sites.

    It is not a guess: SQLite's CURRENT_TIMESTAMP is UTC by definition and every
    Python writer in this repository goes through `as_stored`.
    """
    assert parse_utc("2026-09-01T08:00:00") == parse_utc("2026-09-01T08:00:00+00:00")


def test_an_aware_and_a_naive_stored_value_can_be_compared() -> None:
    """The latent crash this ticket exists to remove.

    `questionnaire_completed_at` is written with `datetime.now(timezone.utc)`;
    every licence column is written naive. They sit in the same database.
    Nothing compares them today -- the first code that does would raise
    `TypeError: can't compare offset-naive and offset-aware datetimes`, in a
    licence check, in production.
    """
    naive_row = "2026-01-01T00:00:00"
    aware_row = "2026-06-01T00:00:00+00:00"

    assert parse_utc(naive_row) < parse_utc(aware_row)

    with pytest.raises(TypeError):
        # The comparison this replaces, shown failing.
        assert datetime.fromisoformat(naive_row) < datetime.fromisoformat(aware_row)


def test_an_absent_expiry_is_not_an_expired_one() -> None:
    """`NULL expires_at` means an unlimited licence, not a lapsed one.

    `is_expired` fails open for exactly this reason: every column it is used
    against treats NULL as "no deadline recorded", and treating absence as
    expiry would lock out the accounts configured never to expire. The code this
    replaces raised `TypeError` on the None instead.
    """
    assert is_expired(None) is False
    assert is_expired("") is False
    assert is_expired("not a timestamp") is False


def test_expiry_compares_against_now() -> None:
    assert is_expired("2020-01-01T00:00:00") is True
    assert is_expired("2099-01-01T00:00:00") is False
    assert is_expired(as_stored(utc_now() - timedelta(seconds=1))) is True
    assert is_expired(as_stored(utc_now() + timedelta(hours=1))) is False


def test_a_written_timestamp_reads_back_as_the_instant_it_was_written() -> None:
    """The round trip, which is the only property the storage format owes."""
    before = utc_now()
    stored = utc_now_iso()
    after = utc_now()

    assert before <= parse_utc(stored) <= after


def test_the_stored_format_is_still_the_naive_one() -> None:
    """Pinned deliberately, because changing it is a migration, not a fix.

    Several of these columns are ordered as strings and both UIs parse them in
    JavaScript, so switching to an offset-bearing format would shift every
    rendered timestamp by the viewer's UTC offset -- the *correct* rendering,
    but not something to spring on a running install inside a bug fix. When that
    follow-up lands it changes `as_stored` and this test, together.
    """
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?", utc_now_iso())


def test_utc_today_is_a_date_not_an_instant() -> None:
    """Age arithmetic is between two calendar dates.

    `patient_manager` compared a birth *date* against a UTC *instant*, which is
    off by a day around a birthday depending on where the machine is standing.
    """
    today = utc_today()

    assert today == utc_now().date()
    assert not isinstance(today, datetime)


# ─────────────────────────────────────────────────────────────────────────────
# The half of the bug that was actually visible
# ─────────────────────────────────────────────────────────────────────────────


def test_the_admin_dashboard_reads_a_zone_less_timestamp_as_utc(child_env) -> None:
    """The user-visible defect, asserted against the shipped JavaScript.

    `new Date("2026-09-01 08:00:00")` is read as *local* by every engine, so in
    UTC+2 the hub's dashboard showed 08:00 for an instant that was 10:00 for the
    person reading it -- while the Online chip next to it, computed server-side
    in UTC, was right. A machine could read as online beside a "last seen" two
    hours stale.

    Asserted by extracting `asUtc` from the page and running it, rather than by
    trusting that the comment above it is still true.
    """
    node = __import__("shutil").which("node")
    if node is None:  # pragma: no cover - CI has node for the frontend build
        pytest.skip("node is not available to exercise the dashboard's JavaScript")

    page = (REPO_ROOT / "src/central_server/admin_ui/index.html").read_text(encoding="utf-8")
    match = re.search(r"function asUtc\(v\) \{[\s\S]*?\n    \}", page)
    assert match, "asUtc has been removed or renamed; the timestamps regress silently"

    script = (
        match.group(0)
        + """
const shown = ['2026-09-01 08:00:00', '2026-09-01T08:00:00',
               '2026-09-01T08:00:00Z', '2026-09-01T08:00:00+00:00']
  .map(v => new Date(asUtc(v)).toISOString());
console.log(JSON.stringify(shown));
"""
    )
    result = __import__("subprocess").run(
        [node, "-e", script],
        capture_output=True,
        text=True,
        # A deliberately non-UTC zone: the whole point of the assertion below
        # is that the timestamps come out identical anyway.
        env=child_env(TZ="Europe/Budapest"),
        check=True,
    )

    instants = __import__("json").loads(result.stdout)
    assert instants == ["2026-09-01T08:00:00.000Z"] * 4, (
        "the dashboard is reading a UTC timestamp as local time again"
    )
