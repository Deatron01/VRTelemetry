# src/infrastructure/persistence/migrations.py
"""Versioned, forward-only schema migrations (VRT-11).

Replaces the pattern that produced VRT-22. Schema evolution was a 167-line
``_initialize_schema`` containing one ``CREATE TABLE IF NOT EXISTS`` followed by
fourteen of these::

    try:
        conn.execute("ALTER TABLE session_metadata ADD COLUMN nasa_tlx_rtlx REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass

That idiom cannot distinguish "already applied" from "genuinely failed", so it
swallows both. It also has no record of what ran: the only way to know a
database's shape is to inspect it. When a column was added to the INSERT and
its matching ``ALTER`` was never written, nothing anywhere noticed -- and every
session's metadata was silently discarded for days.

Here, each migration is numbered, applied exactly once, and recorded. A failure
raises. Applying migrations to a database that predates this table works
correctly: :func:`_baseline_version` inspects the existing schema and marks the
migrations whose effect is already present as applied, so an established
install is not asked to re-add columns it already has.

Adding a migration: append to :data:`MIGRATIONS` with the next number. Never
edit or renumber an existing one -- a database that already ran version 3 will
never run it again, so changing it changes nothing for anyone who has it and
everything for anyone who does not.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.infrastructure.persistence.connection import transaction
from src.utils.logger import logger


@dataclass(frozen=True)
class Migration:
    """One forward-only schema change.

    ``add_columns`` is separate from ``statements`` on purpose. Adding a column
    is the one operation that must be idempotent by *inspection* rather than by
    catching an error: a migration that adds several columns, some of which are
    already present, has to add the rest -- and if the first duplicate aborts
    the statement loop, the later ones are silently skipped.

    That is not hypothetical. The first version of this module caught
    "duplicate column" around the whole migration, so applying it to a database
    missing only the last column added nothing at all, and reported success.
    Which is exactly the failure VRT-22 was. The test for the pre-existing
    database is what caught it.
    """

    version: int
    description: str
    statements: tuple[str, ...] = ()
    add_columns: tuple[tuple[str, str, str], ...] = ()

    #: Columns that must exist for ``statements`` to be meaningful. When one is
    #: absent the statements are skipped and the migration still records itself
    #: as applied.
    #:
    #: This is for optimisations, not for correctness -- an index on a column a
    #: given database does not have is a no-op worth skipping, whereas a column
    #: that fails to be added is data loss. The distinction has to be declared
    #: rather than inferred from an exception, because "swallow the error and
    #: carry on" is precisely the habit this module exists to end.
    requires_columns: tuple[tuple[str, str], ...] = ()

    def apply(self, conn: sqlite3.Connection) -> list[str]:
        """Apply this migration, skipping columns that already exist.

        Returns:
            The columns actually added, for the log. An empty list from a
            migration that declares columns means every one was already there.
        """
        added: list[str] = []
        for table, column in self.requires_columns:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                logger.warning(
                    f"Migration {self.version} skipped: {table}.{column} is not present. "
                    f"This is safe for an index, and would not be for a column addition."
                )
                return []
        for table, column, sql_type in self.add_columns:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
            added.append(f"{table}.{column}")
        for statement in self.statements:
            conn.execute(statement)
        return added


#: Columns added to session_metadata after its original CREATE. Order is the
#: order they were historically added, which is what makes the baseline
#: detection below meaningful.
_SESSION_METADATA_ADDITIONS: tuple[tuple[str, str], ...] = (
    ("patient_id", "TEXT"),
    ("nasa_tlx_temporal", "REAL"),
    ("nasa_tlx_effort", "REAL"),
    ("nasa_tlx_performance", "REAL"),
    ("nasa_tlx_rtlx", "REAL"),
    ("nasa_tlx_band", "TEXT"),
    ("nasa_tlx_raw_items_json", "TEXT"),
    ("ssq_total_severity", "REAL"),
    ("ssq_severity_band", "TEXT"),
    ("ssq_raw_items_json", "TEXT"),
    ("thermal_comfort", "TEXT"),
    ("questionnaire_completed_at", "TEXT"),
    # VRT-22: written by persist_experiment since 27 Aug, declared nowhere.
    ("available_extensions_json", "TEXT"),
)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        description="Baseline session_metadata table",
        statements=(),  # supplied by the repository that owns the table
    ),
    Migration(
        version=2,
        description="Columns added to session_metadata after its original schema",
        add_columns=tuple(
            ("session_metadata", column, sql_type)
            for column, sql_type in _SESSION_METADATA_ADDITIONS
        ),
    ),
    Migration(
        version=3,
        description="Index session_metadata by patient_id for the per-patient listing",
        requires_columns=(("session_metadata", "patient_id"),),
        statements=(
            "CREATE INDEX IF NOT EXISTS idx_session_metadata_patient "
            "ON session_metadata(patient_id)",
        ),
    ),
    Migration(
        version=4,
        description="Index session_metadata by created_at for the ordered listing",
        requires_columns=(("session_metadata", "created_at"),),
        statements=(
            "CREATE INDEX IF NOT EXISTS idx_session_metadata_created "
            "ON session_metadata(created_at DESC)",
        ),
    ),
)


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT    NOT NULL,
            applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    return {row["version"] for row in conn.execute("SELECT version FROM schema_version")}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _baseline_existing_database(conn: sqlite3.Connection) -> None:
    """Record which migrations an established database has already lived through.

    Databases created before this module exists have no ``schema_version``
    table, but they do have the columns. Running the migrations blind would
    fail on the first ``ADD COLUMN`` for a column that is already there --
    correctly, because that failure is now an error rather than a swallowed
    exception. So the first run inspects the schema and marks as applied every
    migration whose effect is already present.

    Deliberately conservative: a migration is only marked applied when *all* of
    its columns exist. A half-applied one is left to run, and the ``ADD COLUMN``
    for a column that does exist is tolerated only here, on this one path.
    """
    columns = _table_columns(conn, "session_metadata")
    if not columns:
        return  # brand new database; migrations run normally

    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (1, "Baseline session_metadata table (pre-existing)"),
    )

    additions = {column for column, _ in _SESSION_METADATA_ADDITIONS}
    if additions <= columns:
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
            (2, "Columns added to session_metadata (pre-existing)"),
        )
        logger.info("Existing database recognised at schema version 2; baselined.")
    else:
        missing = sorted(additions - columns)
        logger.info(
            f"Existing database is missing {len(missing)} column(s); will migrate: {missing}"
        )


def migrate(
    db_path: str | Path,
    *,
    baseline_schema: Callable[[sqlite3.Connection], None] | None = None,
) -> int:
    """Bring ``db_path`` up to the latest schema version.

    Args:
        db_path: Database to migrate.
        baseline_schema: Called to create the initial tables when the database
            is new. The table definition belongs to the repository that owns
            it, not to this module.

    Returns:
        The schema version the database is now at.

    Raises:
        sqlite3.Error: if a migration fails. Deliberately not swallowed -- a
            migration that cannot be applied leaves the database in a shape the
            code does not expect, and continuing is how VRT-22 happened.
    """
    with transaction(db_path) as conn:
        _ensure_version_table(conn)

        is_new = not _table_columns(conn, "session_metadata")
        if is_new and baseline_schema is not None:
            baseline_schema(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
                (1, MIGRATIONS[0].description),
            )
        elif not is_new:
            _baseline_existing_database(conn)

        applied = _applied_versions(conn)
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            added = migration.apply(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
                (migration.version, migration.description),
            )
            detail = f" (added {', '.join(added)})" if added else ""
            logger.info(
                f"Applied schema migration {migration.version}: {migration.description}{detail}"
            )

        return max(_applied_versions(conn), default=0)


def current_version(db_path: str | Path) -> int:
    """Return the schema version of ``db_path``, or 0 if it has never migrated."""
    with transaction(db_path) as conn:
        _ensure_version_table(conn)
        return max(_applied_versions(conn), default=0)
