# src/utils/clock.py
"""The time vocabulary (VRT-21).

Seventeen sites called ``datetime.utcnow()`` and compared the result against a
timestamp read back out of SQLite. This module replaces all of them, and the
reason is not the one the backlog gave -- see "What was actually wrong" below.

Two rules, and they are asymmetric on purpose
---------------------------------------------

**Reading is tolerant.** :func:`parse_utc` accepts everything this application
has ever written: naive ISO from ``datetime.utcnow().isoformat()``, SQLite's
space-separated ``CURRENT_TIMESTAMP``, and offset-aware ISO from
``datetime.now(timezone.utc).isoformat()``. A value with no zone is *assumed
UTC*, which is not a guess -- every writer in this repository produces UTC, and
the assumption is stated here rather than implied at fourteen call sites.

**Comparing is always aware.** :func:`utc_now` returns an offset-aware datetime,
so every comparison has a zone on both sides. Python refuses to compare an aware
datetime with a naive one, and the two kinds are already mixed in this
database -- ``questionnaire_completed_at`` is written aware while every licence
column is written naive. Nothing compares them *today*; the first code that does
raises ``TypeError`` in production, in a licence check.

**Writing is unchanged.** :func:`utc_now_iso` still emits the naive form the
existing rows use. That is deliberate and temporary: several columns are sorted
as strings, the desktop and hub UIs parse them with JavaScript's ``Date``, and
changing the format is a migration rather than a bug fix. Making the *wire*
format explicit is the follow-up recorded against this ticket.

What was actually wrong
-----------------------

The backlog said: "16 naive ``datetime.utcnow()`` compared against stored
ISO-8601 strings for licence expiry. A real correctness bug the moment his hub
and his workstations are not in the same timezone."

That is not what these sites do. ``utcnow()`` is UTC wherever it runs, and every
stored value it is compared against is also UTC, so naive-vs-naive is
timezone-independent and the comparisons are correct on any machine. Three real
defects sat underneath the description:

1. **The zone is missing from the wire, so the reader has to guess.** The hub's
   admin dashboard runs ``new Date("2026-09-01 08:00:00")``, and JavaScript
   reads a zone-less timestamp as *local*. In UTC+2 every "Last Seen", upload
   time and licence date in that dashboard is displayed two hours early -- while
   the Online/Offline chip beside it, computed server-side in UTC, is right. A
   client reads as online next to a last-seen two hours stale.

2. **Aware and naive values already coexist in one database**, one `TypeError`
   away from taking down a licence check.

3. **``datetime.utcnow()`` is deprecated from Python 3.12**, which this project
   claims to support.

The age calculation had its own version of the same confusion: a date of birth
parsed as a naive local date and compared against a UTC instant, which is off by
a day near a birthday depending on where you are standing.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

__all__ = ["as_stored", "is_expired", "parse_utc", "utc_now", "utc_now_iso", "utc_today"]


def utc_now() -> datetime:
    """The current instant, offset-aware, in UTC.

    Replaces ``datetime.utcnow()``, which returns a *naive* datetime holding a
    UTC time -- an object that claims to know nothing about its own zone while
    in fact being in one. Comparisons against it work only as long as everything
    on the other side shares the same unstated convention.
    """
    return datetime.now(timezone.utc)


def utc_today() -> date:
    """Today's date in UTC.

    For age arithmetic, where the other operand is a calendar date rather than
    an instant and comparing the two directly is a category error.
    """
    return utc_now().date()


def utc_now_iso() -> str:
    """Now, as the naive-UTC ISO string this application's columns already hold.

    Naive on purpose. Existing rows are naive, several of these columns are
    ordered as strings, and both UIs parse them in JavaScript -- so switching to
    an offset-bearing format is a data migration with a visible side effect (it
    would shift every rendered timestamp by the viewer's UTC offset, which is
    the *correct* rendering, but not something to spring on a running install
    inside a bug fix).

    Read it back with :func:`parse_utc`, which puts the zone on.
    """
    return as_stored(utc_now())


def as_stored(moment: datetime) -> str:
    """Render an aware datetime in the naive-UTC form these columns hold.

    The one place the "stored timestamps are naive UTC" convention is applied,
    so the follow-up that makes the format explicit is a change to this function
    rather than a search for `.isoformat()`.
    """
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def parse_utc(value: Any) -> datetime | None:
    """Read a stored timestamp as an offset-aware UTC datetime.

    Accepts every shape this repository has written or received:

    * ``"2026-09-01T08:00:00.123456"`` -- ``datetime.utcnow().isoformat()``
    * ``"2026-09-01 08:00:00"`` -- SQLite ``CURRENT_TIMESTAMP``
    * ``"2026-09-01T08:00:00+00:00"`` -- ``datetime.now(timezone.utc)``
    * ``"2026-09-01T08:00:00Z"`` -- what the hub will send once the wire format
      is made explicit; accepted now so that change needs no coordination
    * a ``datetime``, aware or naive

    Args:
        value: The stored value. ``None`` and unparsable input return ``None``
            rather than raising: these are read from columns that are legitimately
            empty, and a caller deciding what an absent expiry means is a
            different decision from a caller handling corrupt data. Every caller
            in this repository treats ``None`` as "no constraint recorded".

    Returns:
        An aware UTC datetime, or ``None``.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        # `fromisoformat` on 3.10 rejects the trailing "Z" that everything else
        # in the world writes. Python 3.11 accepts it; this keeps the 3.10 leg
        # working, and the substitution is exact -- "Z" *is* "+00:00".
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        # Stated, not guessed: every writer in this repository produces UTC.
        # SQLite's CURRENT_TIMESTAMP is UTC by definition, and every Python
        # writer goes through utc_now_iso() above.
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_expired(value: Any, *, grace: timedelta | None = None) -> bool:
    """Whether ``value`` is in the past.

    Args:
        value: A stored timestamp, in any of the shapes :func:`parse_utc` takes.
        grace: Added to the deadline before comparing.

    Returns:
        False when ``value`` is absent or unparsable. An expiry check must fail
        *open* on a missing value, because every column this is used against
        treats NULL as "no expiry" -- an unlimited licence, a session with no
        deadline. Treating absence as expiry would lock out exactly the accounts
        that were configured never to expire.
    """
    deadline = parse_utc(value)
    if deadline is None:
        return False
    if grace is not None:
        deadline = deadline + grace
    return deadline < utc_now()
