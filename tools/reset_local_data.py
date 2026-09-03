#!/usr/bin/env python3
"""Clear this machine's recorded data, ready for a fresh study run.

Between test runs -- and before the first real VR session -- it is useful to
start from nothing: no recordings, no session metadata, no logs, and no copies
sitting on the hub pretending the study has already begun. Doing that by hand
means remembering five directories, three SQLite databases and a set of
bookkeeping tables inside a fourth, which is how a "clean" run ends up carrying
half of the previous one.

Nothing here is recoverable. Two things make that safe enough to automate:

**It refuses to leave the data root.** Every path is resolved and checked
against ``settings.paths.data_root``. On this project the data root *is* the
repository root, which is unusual and worth being paranoid about -- a scope with
a wrong glob would otherwise be able to delete source.

**It refuses to touch anything git tracks.** The five data directories are all
in ``.gitignore`` and nothing under them is tracked, so anything tracked that
matched a scope would mean a scope is wrong. The check costs one subprocess and
turns a bad edit into a refusal instead of a lost file.

And it prints what it would do and exits, unless you pass ``--apply``.

Usage::

    python tools/reset_local_data.py --sessions --hub          # preview
    python tools/reset_local_data.py --sessions --hub --apply  # do it

Stop the desktop app first. A running backend holds the SQLite files open, and
on Windows an open handle makes the delete fail rather than silently succeed.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings


@dataclass
class Plan:
    """What a set of scopes resolves to on this machine.

    Separate from doing it so the preview and the run cannot disagree: the same
    object is printed and then executed.
    """

    #: Files and directories to remove entirely.
    paths: list[Path] = field(default_factory=list)
    #: ``(database, table)`` pairs to empty, keeping the database and its other
    #: tables. Used for the bookkeeping inside ``license_cache.db``, which also
    #: holds this machine's activation and the hub address -- both of which the
    #: session scope must not touch.
    tables: list[tuple[Path, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.paths and not self.tables


def _existing(*candidates: Path) -> Iterator[Path]:
    for path in candidates:
        if path.exists():
            yield path


def _glob(directory: Path, pattern: str) -> Iterator[Path]:
    if directory.exists():
        yield from sorted(directory.glob(pattern))


def build_plan(args: argparse.Namespace) -> Plan:
    """Resolve the requested scopes against this machine's configured paths."""
    paths = get_settings().paths
    plan = Plan()

    if args.sessions:
        plan.paths += list(_glob(paths.sessions_dir, "*.parquet"))
        plan.paths += list(_glob(paths.session_logs_dir, "*.log"))
        plan.paths += list(_glob(paths.logs_dir, "*.log"))
        plan.paths += list(_existing(paths.metadata_db, paths.usage_db))
        # The queues and ledgers that refer to the recordings above. Left
        # behind, they make the next boot sweep hunt for files that no longer
        # exist -- self-healing, but it fills the log of a fresh run with
        # complaints about the previous one. `license_state`, `app_config` and
        # `account_session` are deliberately not in this list: they are the
        # activation and the hub address, which this scope keeps.
        for table in (
            "pending_uploads",
            "pending_session_logs",
            "synced_sessions",
            "synced_session_logs",
        ):
            if paths.license_cache_db.exists():
                plan.tables.append((paths.license_cache_db, table))

    if args.hub:
        plan.paths += list(_existing(paths.central_data_db))
        if paths.central_storage_dir.exists():
            plan.paths += sorted(
                p for p in paths.central_storage_dir.iterdir() if p.name != ".gitkeep"
            )

    if args.patients:
        plan.paths += list(_existing(paths.patients_db))
        if paths.license_cache_db.exists():
            plan.tables.append((paths.license_cache_db, "pending_patient_syncs"))

    if args.activation:
        plan.paths += list(_existing(paths.license_cache_db))

    if args.licences:
        plan.paths += list(_existing(paths.licenses_db))

    # A path can arrive twice when scopes overlap; and a database queued for
    # deletion must not also be queued for a table wipe.
    plan.paths = sorted(set(plan.paths))
    doomed = set(plan.paths)
    plan.tables = [(db, table) for db, table in plan.tables if db not in doomed]
    return plan


def _refuse_outside_data_root(plan: Plan, data_root: Path) -> None:
    """Abort if any resolved path escapes the configured data root."""
    root = data_root.resolve()
    for path in plan.paths + [db for db, _ in plan.tables]:
        resolved = path.resolve()
        if root != resolved and root not in resolved.parents:
            raise SystemExit(
                f"refusing to touch {resolved}: outside the data root {root}. "
                f"A scope in this script is wrong; fix it rather than the check."
            )


def _refuse_tracked_files(plan: Plan, data_root: Path) -> None:
    """Abort if git tracks anything a scope resolved to.

    The data directories are gitignored, so a tracked match means a scope has
    grown a glob it should not have.
    """
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", *[str(p) for p in plan.paths]],
            cwd=data_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[!] Could not consult git ({exc}); skipping the tracked-file check.")
        return

    names = [n for n in tracked.split("\0") if n]
    if names:
        listed = "\n    ".join(names[:20])
        raise SystemExit(
            f"refusing to delete {len(names)} file(s) that git tracks:\n    {listed}\n"
            f"These are source, not data. A scope in this script is wrong."
        )


def _size_of(path: Path) -> int:
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _human(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def describe(plan: Plan, data_root: Path) -> int:
    """Print the plan. Returns the total bytes it would free."""
    total = 0
    for path in plan.paths:
        size = _size_of(path)
        total += size
        try:
            shown = path.relative_to(data_root)
        except ValueError:  # pragma: no cover - _refuse_outside_data_root ran first
            shown = path
        print(f"    [-] {shown}  ({_human(size)})")

    for db, table in plan.tables:
        print(f"    [~] {db.relative_to(data_root)}  empty table: {table}")

    return total


def apply(plan: Plan) -> None:
    """Carry the plan out. Failures are reported per item, not fatal.

    A file held open by a running backend is the expected failure on Windows,
    and one locked file should not abandon the rest of the sweep -- but every
    failure is printed, because a reset that silently left something behind is
    worse than one that did not run.
    """
    removed = 0
    for path in plan.paths:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed += 1
        except OSError as exc:
            print(f"    [!] could not remove {path.name}: {exc}")

    for db, table in plan.tables:
        try:
            with sqlite3.connect(db) as conn:
                conn.execute(f"DELETE FROM {table}")  # noqa: S608 - name from this file's own list
                conn.commit()
        except sqlite3.Error as exc:
            print(f"    [!] could not clear {db.name}:{table}: {exc}")

    print(
        f"\n[+] Removed {removed}/{len(plan.paths)} path(s), cleared {len(plan.tables)} table(s)."
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clear recorded data so the next run starts from nothing.",
        epilog="Nothing is deleted without --apply.",
    )
    parser.add_argument(
        "--sessions",
        action="store_true",
        help="Recordings, session logs, session metadata, usage events, and the "
        "upload queues that refer to them. Keeps the activation and hub address.",
    )
    parser.add_argument(
        "--hub",
        action="store_true",
        help="The central server's own copies: central_data.db and CentralStorage.",
    )
    parser.add_argument(
        "--patients",
        action="store_true",
        help="Patient records and their pending syncs. You will re-enter consent.",
    )
    parser.add_argument(
        "--activation",
        action="store_true",
        help="This machine's licence cache: activation, hub address and account "
        "session. You will re-activate against the hub.",
    )
    parser.add_argument(
        "--licences",
        action="store_true",
        help="The licence server's database: organisation, admin user, licence "
        "keys and machine activations. You will bootstrap an admin again.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Everything except --licences.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without it this prints the plan and exits.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.all:
        args.sessions = args.hub = args.patients = args.activation = True

    scopes = [
        name
        for name in ("sessions", "hub", "patients", "activation", "licences")
        if getattr(args, name)
    ]
    if not scopes:
        build_arg_parser().print_help()
        print("\n[!] Choose at least one scope. Nothing was touched.")
        return 2

    data_root = get_settings().paths.data_root
    plan = build_plan(args)
    _refuse_outside_data_root(plan, data_root)
    _refuse_tracked_files(plan, data_root)

    print(f"[>] Data root: {data_root}")
    print(f"[>] Scopes:    {', '.join(scopes)}\n")

    if plan.is_empty():
        print("[✓] Nothing matched — already clean.")
        return 0

    total = describe(plan, data_root)
    print(f"\n[>] {len(plan.paths)} path(s), {_human(total)}.")

    if not args.apply:
        print("[i] Dry run. Re-run with --apply to delete. Stop the desktop app first.")
        return 0

    print("[>] Applying...\n")
    apply(plan)
    print("[✓] Done. The next boot recreates the databases at the current schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
