"""Tests for the session repository, connections and migrations (VRT-11).

The migration tests carry the weight here. The pattern they replace -- one
``CREATE TABLE IF NOT EXISTS`` followed by fourteen ``ALTER TABLE`` calls each
wrapped in ``except sqlite3.OperationalError: pass`` -- is what produced VRT-22,
where a column was added to an INSERT and its ``ALTER`` was never written, and
every session's metadata was discarded for days without a single error anyone
saw.

So the property under test is not "migrations run". It is: **a database in any
prior state converges on the current schema, and says so.**

One of these caught a real bug in the first version of this module. Migration 2
adds thirteen columns; applied to a database that already had twelve of them,
the first duplicate aborted the statement loop and the thirteenth -- the one
VRT-22 is about -- was never added, while the migration recorded itself as
applied. Column addition is now idempotent by inspection rather than by catching
an error.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from src.infrastructure.persistence.connection import transaction
from src.infrastructure.persistence.migrations import MIGRATIONS, current_version
from src.infrastructure.persistence.session_repository import SessionRepository

LATEST_VERSION = max(m.version for m in MIGRATIONS)


def _columns(db_path: Path, table: str = "session_metadata") -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def repo(tmp_path: Path) -> SessionRepository:
    return SessionRepository(tmp_path / "vr_metadata.db")


@pytest.fixture
def seeded(repo: SessionRepository) -> SessionRepository:
    with transaction(repo.db_path) as conn:
        conn.execute(
            "INSERT INTO session_metadata (session_id, subject_id, patient_id, hmd_model) "
            "VALUES (?, ?, ?, ?)",
            ("20260527_133428", "SUB_TEST_01", "pat-1", "Valve Index"),
        )
    return repo


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #


def test_a_new_database_arrives_at_the_latest_version(repo: SessionRepository) -> None:
    assert current_version(repo.db_path) == LATEST_VERSION


def test_a_new_database_has_every_column_including_the_vrt22_one(repo: SessionRepository) -> None:
    columns = _columns(repo.db_path)

    assert "available_extensions_json" in columns
    assert "questionnaire_completed_at" in columns
    assert "nasa_tlx_rtlx" in columns


def test_migrating_is_idempotent(repo: SessionRepository) -> None:
    """Constructing a second repository over the same file must be a no-op."""
    before = _columns(repo.db_path)

    SessionRepository(repo.db_path)
    SessionRepository(repo.db_path)

    assert _columns(repo.db_path) == before
    assert current_version(repo.db_path) == LATEST_VERSION


def test_an_existing_database_is_baselined_not_rebuilt(tmp_path: Path) -> None:
    """A database from before this module has no schema_version but has the columns.

    Running the migrations blind would fail on the first ADD COLUMN. The first
    run must recognise what is already there.
    """
    db = tmp_path / "legacy.db"
    SessionRepository(db)
    with transaction(db) as conn:
        conn.execute(
            "INSERT INTO session_metadata (session_id, subject_id) VALUES ('old', 'SUB_OLD')"
        )
        conn.execute("DROP TABLE schema_version")

    repo = SessionRepository(db)

    assert current_version(db) == LATEST_VERSION
    assert repo.get("old")["subject_id"] == "SUB_OLD"


def test_a_database_missing_only_the_last_column_still_gets_it(tmp_path: Path) -> None:
    """The regression test for the bug this module shipped with.

    Bence's database is in exactly this state: created before
    ``available_extensions_json`` existed, so twelve of migration 2's thirteen
    columns are present and one is not. The first implementation caught
    "duplicate column" around the whole migration, so the first already-present
    column aborted the loop, the missing one was never added, and the migration
    recorded itself as applied. Silently. Which is VRT-22 again, one layer up.
    """
    db = tmp_path / "older.db"
    SessionRepository(db)

    # Rebuild the table without the VRT-22 column and forget the bookkeeping.
    with sqlite3.connect(db) as conn:
        keep = [
            row[1]
            for row in conn.execute("PRAGMA table_info(session_metadata)")
            if row[1] != "available_extensions_json"
        ]
        conn.execute("CREATE TABLE rebuilt (" + ", ".join(f"{c} TEXT" for c in keep) + ")")
        conn.execute("INSERT INTO rebuilt (session_id, subject_id) VALUES ('old', 'SUB_OLD')")
        conn.execute("DROP TABLE session_metadata")
        conn.execute("ALTER TABLE rebuilt RENAME TO session_metadata")
        conn.execute("DROP TABLE schema_version")

    assert "available_extensions_json" not in _columns(db)

    repo = SessionRepository(db)

    assert "available_extensions_json" in _columns(db), "the missing column was skipped again"
    assert repo.get("old")["subject_id"] == "SUB_OLD", "existing data was lost"


def test_migration_versions_are_unique_and_contiguous() -> None:
    """A duplicate or a gap means someone edited history instead of appending."""
    versions = [m.version for m in MIGRATIONS]

    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions == list(range(1, len(versions) + 1))


# --------------------------------------------------------------------------- #
# Connection configuration
# --------------------------------------------------------------------------- #


def test_connections_use_wal_so_reads_do_not_block_on_the_sync_thread(
    repo: SessionRepository,
) -> None:
    with transaction(repo.db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"] == "wal"


def test_connections_enforce_foreign_keys(repo: SessionRepository) -> None:
    """Off by default per connection, which makes a REFERENCES clause decorative."""
    with transaction(repo.db_path) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"] == 1


def test_connections_wait_rather_than_failing_on_a_locked_database(
    repo: SessionRepository,
) -> None:
    """SQLite's default busy timeout is zero: a contended writer errors instantly.

    This application has a sync thread and a heartbeat thread writing while the
    API reads, so zero is the wrong default.
    """
    with transaction(repo.db_path) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()["timeout"] >= 1000


def test_the_transaction_helper_closes_the_connection(tmp_path: Path) -> None:
    """`with sqlite3.connect(...)` commits but does NOT close -- every such block
    in the old code leaked a handle, and on Windows a file lock with it."""
    db = tmp_path / "closes.db"
    with transaction(db) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_a_failed_transaction_rolls_back(repo: SessionRepository) -> None:
    with pytest.raises(sqlite3.IntegrityError), transaction(repo.db_path) as conn:
        conn.execute("INSERT INTO session_metadata (session_id, subject_id) VALUES ('a','A')")
        conn.execute("INSERT INTO session_metadata (session_id, subject_id) VALUES ('a','A')")

    assert repo.get("a") == {}


def test_rows_come_back_as_dicts_not_sqlite_row(repo: SessionRepository) -> None:
    """sqlite3.Row is not a Mapping: it serialises to JSON as a list, dropping
    every column name. These rows go straight into API responses."""
    with transaction(repo.db_path) as conn:
        row = conn.execute("SELECT 1 AS answer").fetchone()

    assert isinstance(row, dict)
    assert row == {"answer": 1}


def test_concurrent_writers_do_not_error(repo: SessionRepository) -> None:
    """The condition the busy timeout exists for, exercised rather than asserted."""
    errors: list[Exception] = []

    def write(n: int) -> None:
        try:
            for i in range(20):
                with transaction(repo.db_path) as conn:
                    conn.execute(
                        "INSERT INTO session_metadata (session_id, subject_id) VALUES (?, ?)",
                        (f"s{n}_{i}", f"SUB{n}"),
                    )
        except Exception as exc:  # noqa: BLE001 - the whole point is to catch anything
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writes failed: {errors}"
    assert len(repo.list_all()) == 80


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def test_the_listing_returns_exactly_the_columns_the_frontend_reads(
    seeded: SessionRepository,
) -> None:
    rows = seeded.list_for_api()

    assert len(rows) == 1
    assert set(rows[0]) == set(SessionRepository.LISTING_COLUMNS)


def test_get_returns_the_full_row(seeded: SessionRepository) -> None:
    row = seeded.get("20260527_133428")

    assert row["subject_id"] == "SUB_TEST_01"
    assert len(row) > 20


def test_get_on_an_unknown_session_returns_empty_not_none(seeded: SessionRepository) -> None:
    """Callers test truthiness; None and {} both work, but only one is consistent."""
    assert seeded.get("nope") == {}


def test_sessions_for_a_patient_are_scoped_to_that_patient(seeded: SessionRepository) -> None:
    with transaction(seeded.db_path) as conn:
        conn.execute(
            "INSERT INTO session_metadata (session_id, subject_id, patient_id) VALUES (?,?,?)",
            ("other", "SUB_OTHER", "pat-2"),
        )

    assert [r["session_id"] for r in seeded.list_for_patient("pat-1")] == ["20260527_133428"]


def test_exists_does_not_fetch_eighty_columns(seeded: SessionRepository) -> None:
    assert seeded.exists("20260527_133428")
    assert not seeded.exists("nope")


# --------------------------------------------------------------------------- #
# Guarded writes
# --------------------------------------------------------------------------- #


def test_update_writes_allowed_columns(seeded: SessionRepository) -> None:
    updated, written = seeded.update("20260527_133428", {"session_rating": 4})

    assert updated
    assert written == ["session_rating"]
    assert seeded.get("20260527_133428")["session_rating"] == 4


def test_update_drops_columns_outside_the_allowlist(seeded: SessionRepository) -> None:
    """The guarantee that used to live in a Pydantic model two packages away."""
    updated, written = seeded.update(
        "20260527_133428", {"session_rating": 3, "subject_age": 99, "created_at": "hacked"}
    )

    assert written == ["session_rating"]
    row = seeded.get("20260527_133428")
    assert row["subject_age"] is None
    assert updated


def test_a_column_name_that_is_sql_is_dropped_not_interpolated(seeded: SessionRepository) -> None:
    """Column names cannot be parameterised, so the allowlist is the whole defence."""
    updated, written = seeded.update(
        "20260527_133428", {"session_rating = 1; DROP TABLE session_metadata; --": 1}
    )

    assert not updated
    assert written == []
    assert seeded.exists("20260527_133428"), "the table is gone"


def test_updating_an_unknown_session_reports_no_row(seeded: SessionRepository) -> None:
    updated, written = seeded.update("nope", {"session_rating": 4})

    assert not updated
    assert written == ["session_rating"]


def test_questionnaire_columns_are_a_separate_allowlist(seeded: SessionRepository) -> None:
    """A questionnaire may not rewrite subject_id, and an edit may not fake a score."""
    assert "subject_id" not in SessionRepository.QUESTIONNAIRE_COLUMNS
    assert "ssq_total_severity" not in SessionRepository.EDITABLE_COLUMNS

    assert seeded.save_questionnaire("20260527_133428", {"ssq_total_severity": 22.4})
    assert seeded.get("20260527_133428")["ssq_total_severity"] == 22.4


def test_saving_an_empty_questionnaire_reports_failure(seeded: SessionRepository) -> None:
    assert not seeded.save_questionnaire("20260527_133428", {"not_a_column": 1})


def test_no_module_outside_persistence_imports_sqlite3() -> None:
    """The rule this layer exists to enforce, checked rather than trusted.

    Scoped to the workstation side. The central hub and the licence service
    still open their own connections; they are separate deployables and moving
    them is VRT-15, where the bounded contexts are drawn.
    """
    import re

    root = Path(__file__).resolve().parents[2] / "src"
    offenders = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if re.search(r"^import sqlite3", path.read_text(encoding="utf-8"), re.M)
        and "infrastructure/persistence" not in path.as_posix()
    ]

    allowed = {
        "central_server/data_manager.py",
        "central_server/data_schema.py",
        "license_service/auth_manager.py",
        "license_service/db_schema.py",
        "license_service/local_cache.py",
        "license_service/manager.py",
        "patients/patient_manager.py",
        "storage/database_manager.py",
        "storage/usage_tracker.py",
    }
    assert set(offenders) <= allowed, f"new raw sqlite3 usage: {sorted(set(offenders) - allowed)}"
    assert "interfaces/api/routers/sessions.py" not in offenders


def test_an_index_migration_is_skipped_when_its_column_is_absent(tmp_path: Path) -> None:
    """Optimisations degrade; column additions do not.

    A database whose table lacks `created_at` -- possible for a hand-built or
    partially-restored file -- must still migrate. Creating an index on a
    missing column is a no-op worth skipping. Adding a *column* that is missing
    never is, and the test above proves that path still runs.

    The distinction is declared on the Migration (`requires_columns`) rather
    than inferred by catching the exception, because "swallow it and carry on"
    is the habit that produced VRT-22.
    """
    db = tmp_path / "no_created_at.db"
    with transaction(db) as conn:
        conn.execute("CREATE TABLE session_metadata (session_id TEXT PRIMARY KEY, subject_id TEXT)")
        conn.execute("INSERT INTO session_metadata VALUES ('s1', 'SUB')")

    repo = SessionRepository(db)

    assert repo.get("s1")["subject_id"] == "SUB"
    assert "available_extensions_json" in _columns(db), "columns must still be added"
    indexes = [r[1] for r in sqlite3.connect(db).execute("PRAGMA index_list(session_metadata)")]
    assert "idx_session_metadata_created" not in indexes
    assert "idx_session_metadata_patient" in indexes, (
        "patient_id exists, so its index should be made"
    )
