# src/infrastructure/persistence/connection.py
"""One place where SQLite connections are opened and configured (VRT-11).

Every module that touched a database opened its own connection with its own
settings -- or rather, with none. ``sqlite3.connect(path)`` was called in ten
places and the only thing any of them configured was a row factory, and not
consistently. That left three defaults in force that are wrong for this
application:

**No busy timeout.** SQLite's default is zero: a writer that finds the database
locked fails *immediately* with ``database is locked``. This application has a
background sync thread writing upload state every 20 seconds, a heartbeat
thread every 30, and an API serving reads from a third. Under the default,
those collide and the loser errors out rather than waiting the few milliseconds
the other needs. Set to five seconds here.

**Journal mode ``DELETE``.** A single writer blocks every reader for the
duration of its transaction. WAL lets readers proceed while a write is in
flight, which is exactly the shape of this workload: one background writer,
several readers.

**Foreign keys off.** SQLite disables enforcement per connection unless asked,
so a declared ``REFERENCES`` clause is documentation rather than a constraint.

None of this is exotic; it is the configuration almost every SQLite application
needs and almost none sets, because the defaults are quiet rather than loud.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

#: How long a blocked writer waits before giving up. Five seconds is far longer
#: than any transaction here legitimately takes, so hitting it means something
#: is genuinely wrong rather than merely contended.
BUSY_TIMEOUT_SECONDS = 5.0


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    """Row factory yielding plain dicts.

    Chosen over ``sqlite3.Row`` because rows travel straight into JSON
    responses. ``sqlite3.Row`` supports indexing but is not a Mapping, so it
    serialises as a list and silently drops every column name.
    """
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


def connect(db_path: str | Path, *, row_factory: bool = True) -> sqlite3.Connection:
    """Open a configured connection to ``db_path``.

    Creates the parent directory if it does not exist, so a caller never has to
    remember to.

    Args:
        db_path: File to open. ``:memory:`` is honoured for tests.
        row_factory: Return rows as dicts. Set False when the caller wants
            tuples, which is only worth doing for large scans.

    Returns:
        A connection with WAL, foreign keys, and a busy timeout applied.
    """
    path = Path(db_path)
    if str(db_path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_SECONDS)
    if row_factory:
        conn.row_factory = _row_to_dict

    # WAL is a property of the database file, not the connection, so this is a
    # no-op after the first time. It cannot be set on an in-memory database.
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_SECONDS * 1000)}")
    return conn


def describe_health(db_path: str | Path) -> str:
    """Whether ``db_path`` opens and answers a trivial query.

    Lives here rather than in the caller because that caller is
    ``GET /health`` on the hub, and writing the probe there would mean an
    ``import sqlite3`` outside this package -- the one thing
    ``test_no_module_outside_persistence_imports_sqlite3`` exists to stop. A
    health check is not a good reason to make an exception to a layering rule;
    it is a good reason for the layer to offer the check.

    Returns a string rather than raising or returning a bool: the caller reports
    it to a human who needs to know *what* is wrong, and "the file is locked" and
    "the file is not a database" call for very different next steps.

    Args:
        db_path: Database to probe.

    Returns:
        ``"ok"``, or a description of why not.
    """
    try:
        with transaction(db_path) as conn:
            conn.execute("SELECT 1")
    except sqlite3.Error as exc:
        return f"error: {exc}"
    except OSError as exc:
        # The directory is gone or unwritable, which `connect` hits while
        # creating the parent rather than while talking to SQLite.
        return f"unavailable: {exc}"
    return "ok"


@contextmanager
def transaction(db_path: str | Path, *, row_factory: bool = True) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on failure, always close.

    ``sqlite3.Connection`` is itself a context manager, but a misleading one: it
    commits or rolls back and **does not close the connection**. Every
    ``with sqlite3.connect(...) as conn`` in this codebase therefore leaked a
    handle, which on Windows also keeps a lock on the file. This closes.

    Args:
        db_path: Database to open.
        row_factory: Passed through to :func:`connect`.

    Yields:
        The open connection.
    """
    conn = connect(db_path, row_factory=row_factory)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
