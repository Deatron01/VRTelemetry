# tests/unit/test_reset_local_data.py
"""Guards on the reset tool.

``tools/reset_local_data.py`` deletes irreversibly, and on this project the
configured data root *is* the repository root -- so a scope with a wrong glob
could reach source. The tool has two refusals for that, and refusals are worth
testing precisely because the situation they cover should never arise: nothing
else will exercise them.

The scopes themselves are not tested against real directories. The tool prints
its plan and does nothing without ``--apply``, so the preview is the check that
matters and it is performed by a person, once, against the machine in front of
them.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest

from tools.reset_local_data import Plan, _refuse_outside_data_root, _refuse_tracked_files, apply


def _args(**scopes: bool) -> argparse.Namespace:
    defaults = {
        "sessions": False,
        "hub": False,
        "patients": False,
        "activation": False,
        "licences": False,
    }
    defaults.update(scopes)
    return argparse.Namespace(**defaults)


def test_a_path_outside_the_data_root_is_refused(tmp_path: Path) -> None:
    """The one that matters. A scope that escapes stops the run."""
    plan = Plan(paths=[tmp_path.parent / "somewhere_else" / "source.py"])

    with pytest.raises(SystemExit) as caught:
        _refuse_outside_data_root(plan, tmp_path)

    assert "outside the data root" in str(caught.value)
    assert "fix it rather than the check" in str(caught.value)


def test_a_table_wipe_outside_the_data_root_is_refused(tmp_path: Path) -> None:
    """Databases are checked too, not only the paths queued for deletion."""
    plan = Plan(tables=[(tmp_path.parent / "elsewhere.db", "pending_uploads")])

    with pytest.raises(SystemExit):
        _refuse_outside_data_root(plan, tmp_path)


def test_paths_inside_the_data_root_are_allowed(tmp_path: Path) -> None:
    (tmp_path / "Sessions").mkdir()
    plan = Plan(paths=[tmp_path / "Sessions" / "vr_telemetry_1.parquet"])

    _refuse_outside_data_root(plan, tmp_path)  # does not raise


def test_a_tracked_file_is_refused(tmp_path: Path) -> None:
    """Git tracking a match means a scope has grown a glob it should not have.

    The data directories are all gitignored, so this can only fire on a bad
    edit -- which is exactly when it is wanted.
    """
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tracked = tmp_path / "engine.py"
    tracked.write_text("# source, not data\n", encoding="utf-8")
    subprocess.run(["git", "add", "engine.py"], cwd=tmp_path, check=True)

    with pytest.raises(SystemExit) as caught:
        _refuse_tracked_files(Plan(paths=[tracked]), tmp_path)

    assert "git tracks" in str(caught.value)
    assert "engine.py" in str(caught.value)


def test_a_locked_file_is_reported_and_the_rest_still_go(tmp_path: Path, capsys) -> None:
    """One file the backend still holds must not abandon the sweep.

    That is the expected failure on Windows, where an open handle makes the
    delete fail rather than silently succeed -- but it is reported, because a
    reset that quietly left something behind is worse than one that did not run.
    """
    survivor = tmp_path / "gone.parquet"
    survivor.write_bytes(b"x")
    missing = tmp_path / "never_existed.parquet"

    apply(Plan(paths=[missing, survivor]))

    out = capsys.readouterr().out
    assert not survivor.exists()
    assert "could not remove never_existed.parquet" in out
    assert "Removed 1/2 path(s)" in out


def test_clearing_a_table_keeps_the_database_and_its_other_tables(tmp_path: Path) -> None:
    """The session scope empties the upload queues and keeps the activation.

    Deleting `license_cache.db` outright would take the machine's activation and
    the hub address with it, which is a different scope with a different flag.
    """
    db = tmp_path / "license_cache.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE pending_uploads (session_id TEXT)")
        conn.execute("CREATE TABLE license_state (activation_id TEXT)")
        conn.execute("INSERT INTO pending_uploads VALUES ('20260812_175203')")
        conn.execute("INSERT INTO license_state VALUES ('ACT-1')")
        conn.commit()

    apply(Plan(tables=[(db, "pending_uploads")]))

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_uploads").fetchone()[0] == 0
        assert conn.execute("SELECT activation_id FROM license_state").fetchone()[0] == "ACT-1"


def test_no_scope_deletes_nothing(tmp_path: Path) -> None:
    """`--all` aside, a scope has to be asked for by name."""
    from tools.reset_local_data import build_plan

    assert build_plan(_args()).is_empty()
