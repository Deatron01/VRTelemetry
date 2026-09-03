"""Regression tests for session metadata persistence (VRT-22).

``DatabaseManager.persist_experiment()`` could not write a row. Two independent
defects, either one sufficient:

1. The INSERT named 68 columns and supplied 73 ``?`` placeholders, so SQLite
   raised ``73 values for 68 columns``.
2. It wrote ``available_extensions_json``, a column that ``CREATE TABLE`` never
   declared and no migration ever added.

Both were invisible in normal use. ``persist_experiment`` catches
``sqlite3.Error`` and logs it, and ``TelemetryEngine.start()`` treats a failed
persist as a warning and keeps recording -- deliberately, so a metadata problem
never costs a session's telemetry. The consequence is that every recording
wrote its Parquet frames correctly and its metadata row not at all.

These tests assert on the observable outcome -- a row exists and can be read
back -- rather than on the SQL, so they keep their meaning when VRT-11 replaces
the storage layer with a repository.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.infrastructure.persistence.migrations import _SESSION_PROFILE_COLUMNS
from src.storage.database_manager import SESSION_METADATA_COLUMNS, DatabaseManager


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    """A DatabaseManager over a database that did not exist a moment ago.

    The `fresh` part matters: a database created by an older build might have
    picked the missing column up by accident, which is how a bug like this hides
    on the machine of whoever wrote it.
    """
    return DatabaseManager(db_path=str(tmp_path / "vr_metadata.db"))


SAMPLE_METADATA = {
    "M-IV_Static_Metadata": {
        "session_id": "20260527_133428",
        "subject_id": "SUB_TEST_01",
        "patient_id": "pat-1",
        "start_timestamp_utc": "2026-05-27T13:34:28+00:00",
        "subject_age": 31,
        "hmd_refresh_rate": 90.0,
    },
    "H-VII_Hardware_Capabilities": {
        "openxr_runtime": "SteamVR/OpenXR",
        "hmd_model": "Valve Index",
        "has_eye_tracking": True,
        "available_extensions": ["XR_EXT_eye_gaze_interaction", "XR_FB_face_tracking"],
    },
    "C-V_Calibration": {"dominant_hand": "left", "arm_length_left": 0.748},
    "S-IX_System_Profile": {"os_name": "Windows", "cpu_cores_logical": 16},
}


def test_persist_experiment_writes_a_row_to_a_fresh_database(db: DatabaseManager) -> None:
    """The headline regression: this wrote nothing at all, on every machine."""
    db.persist_experiment(SAMPLE_METADATA)

    row = db.get_session_row("20260527_133428")

    assert row is not None, "persist_experiment silently wrote no row"
    assert row["subject_id"] == "SUB_TEST_01"
    assert row["patient_id"] == "pat-1"


def test_every_metadata_category_reaches_its_column(db: DatabaseManager) -> None:
    """persist_experiment flattens five nested category dicts; all five land."""
    db.persist_experiment(SAMPLE_METADATA)
    row = db.get_session_row("20260527_133428")

    assert row["subject_age"] == 31  # M-IV static
    assert row["hmd_model"] == "Valve Index"  # H-VII hardware
    assert row["dominant_hand"] == "left"  # C-V calibration
    assert row["os_name"] == "Windows"  # S-IX system profile
    assert row["hmd_refresh_rate"] == 90.0


def test_available_extensions_are_stored_as_json(db: DatabaseManager) -> None:
    """The column that CREATE TABLE never declared."""
    import json

    db.persist_experiment(SAMPLE_METADATA)
    row = db.get_session_row("20260527_133428")

    assert json.loads(row["available_extensions_json"]) == [
        "XR_EXT_eye_gaze_interaction",
        "XR_FB_face_tracking",
    ]


def test_the_column_list_and_the_placeholder_list_cannot_drift(db: DatabaseManager) -> None:
    """The statement is derived from one tuple, so a count mismatch is impossible.

    This is the test that would have caught the original defect. It asserts the
    property rather than a number, so adding a column to
    SESSION_METADATA_COLUMNS does not make it fail spuriously.
    """
    assert len(SESSION_METADATA_COLUMNS) == len(set(SESSION_METADATA_COLUMNS)), (
        "duplicate column name in SESSION_METADATA_COLUMNS"
    )

    # Every declared column must actually exist on the table.
    with sqlite3.connect(db.db_path) as conn:
        actual = {r[1] for r in conn.execute("PRAGMA table_info(session_metadata)")}
    missing = [c for c in SESSION_METADATA_COLUMNS if c not in actual]
    assert not missing, f"INSERT names columns the schema does not have: {missing}"


def test_a_minimal_metadata_dict_still_persists(db: DatabaseManager) -> None:
    """Defaults cover every absent field; a sparse dict must not raise."""
    db.persist_experiment({"M-IV_Static_Metadata": {"session_id": "20260101_000000"}})

    row = db.get_session_row("20260101_000000")

    assert row is not None
    assert row["subject_id"] == "UNKNOWN"


def test_an_older_database_is_migrated_rather_than_broken(tmp_path: Path) -> None:
    """A database predating the column gains it on the next DatabaseManager init.

    Bence's existing vr_metadata.db is in exactly this state, so the ALTER TABLE
    path is the one that runs in the field -- and it is the one that would go
    unexercised if the tests only ever built fresh databases.
    """
    db_path = tmp_path / "legacy.db"

    # Build a table that has everything except the column added by VRT-22.
    legacy_columns = [c for c in SESSION_METADATA_COLUMNS if c != "available_extensions_json"]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE session_metadata (" + ", ".join(f"{c} TEXT" for c in legacy_columns) + ")"
        )
        conn.commit()

    db = DatabaseManager(db_path=str(db_path))
    db.persist_experiment(SAMPLE_METADATA)

    assert db.get_session_row("20260527_133428") is not None


def test_a_database_predating_the_system_profile_columns_is_migrated(tmp_path: Path) -> None:
    """The second instance of VRT-22, found in VRT-14 and fixed by migration 5.

    Fourteen system-profile columns were appended to ``SESSION_METADATA_SCHEMA``
    when ``collect_system_profile()`` started travelling inside session
    metadata. A new database gets them from the CREATE TABLE; no migration ever
    added them to an existing one. ``persist_experiment`` names all 68 columns
    in a single INSERT, so a table missing any of them rejects the *whole*
    statement -- not one session's metadata was written on an established
    install.

    That is what Bence's ``Sessions/vr_metadata.db`` looked like when this was
    found: 66 columns, baselined at schema version 2, 15 rows, all of them
    predating the change.

    The test above builds a legacy table missing one column and passes without
    migration 5, because ``_baseline_existing_database`` marks that column's
    migration unapplied and it runs. This one omits the columns that no
    migration covers, which is the real field shape.
    """
    db_path = tmp_path / "pre_profile.db"
    profile_columns = {name for name, _ in _SESSION_PROFILE_COLUMNS}
    legacy_columns = [c for c in SESSION_METADATA_COLUMNS if c not in profile_columns]
    assert len(legacy_columns) == len(SESSION_METADATA_COLUMNS) - 14

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE session_metadata (" + ", ".join(f"{c} TEXT" for c in legacy_columns) + ")"
        )
        conn.execute("INSERT INTO session_metadata (session_id) VALUES ('20260101_000000')")
        conn.commit()

    db = DatabaseManager(db_path=str(db_path))

    assert db.persist_experiment(SAMPLE_METADATA) is True
    assert db.get_session_row("20260527_133428") is not None

    with sqlite3.connect(db_path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(session_metadata)")}
        surviving = conn.execute(
            "SELECT COUNT(*) FROM session_metadata WHERE session_id = '20260101_000000'"
        ).fetchone()[0]

    assert profile_columns <= columns
    assert surviving == 1, "migrating an established database must not disturb its rows"


def test_persist_experiment_reports_whether_it_wrote(tmp_path: Path) -> None:
    """The return value the engine branches on, which was annotated ``-> None``.

    ``src.storage.database_manager`` is in mypy's ignore list, so nothing
    checked the annotation against the body until VRT-14 declared
    ``SessionMetadataSink`` and the checker compared the two. The body was
    always right; the signature was always wrong. This pins the behaviour so
    the signature cannot drift back.
    """
    db = DatabaseManager(db_path=str(tmp_path / "returns.db"))

    assert db.persist_experiment(SAMPLE_METADATA) is True

    with sqlite3.connect(tmp_path / "returns.db") as conn:
        conn.execute("DROP TABLE session_metadata")
        conn.commit()

    assert db.persist_experiment(SAMPLE_METADATA) is False
