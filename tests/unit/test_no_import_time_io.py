"""Importing a module must not do anything (VRT-12).

This is the acceptance criterion for the composition root, expressed as a test
rather than as a promise in a docstring. It imports every module under ``src/``
in a subprocess with ``sqlite3.connect``, ``builtins.open`` and
``socket.socket`` replaced by functions that raise, and asserts none of them
fire.

Why this is worth a test of its own
-----------------------------------

Import-time work is the defect that produced almost every other defect in this
refactor's backlog. ``src/main.py`` opened three SQLite databases, built two
HTTP uploaders and read the licence cache at module scope, and the consequences
compounded:

* The API had zero test coverage for its entire life, because a test could not
  construct a second application, and could not substitute a fake for something
  that was already built and bound before the test ran.
* The acquisition CLI paid for the API's databases on every run and never
  touched them.
* Editing the hub address did nothing until the app restarted, because the
  uploaders had captured it at import.
* ``import src.core.telemetry_frame`` -- a dataclass -- transitively imported
  every VR backend, which is why VRT-5.1 exists.

Nothing prevents that creeping back in except something that fails when it
does. This is that something.

Running in a subprocess is deliberate: by the time pytest collects this file,
half of ``src`` is already imported by other tests, and clearing ``sys.modules``
in-process leaves the parent interpreter in a state later tests inherit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Executed in a clean interpreter. Guards are installed *before* the first
#: `src` import, so anything a module does at import time is caught.
_PROBE = r"""
import builtins
import importlib
import json
import pkgutil
import socket
import sqlite3
import sys

sys.path.insert(0, {repo!r})

SRC = {repo!r} + "/src/"

violations = []
current_module = [""]
armed = [False]


# Whether the code that made this call is ours, rather than a library's.
#
# Walks outward from the probe to the first frame that comes from a real file,
# skipping <frozen importlib._bootstrap> and friends. If that frame lives under
# src/, this repository did the I/O. If it lives in site-packages, a library
# did -- `import psutil` reads /proc/stat and `import pandas` reads the timezone
# database, and neither is this test's business even though our own import
# statement sits further up the same stack.
def blamed_on_this_repo():
    frame = sys._getframe(2)
    while frame is not None:
        filename = frame.f_code.co_filename
        if not filename.startswith("<"):
            return filename.startswith(SRC)
        frame = frame.f_back
    return False


def guard(label, original):
    def probe(*args, **kwargs):
        if armed[0] and blamed_on_this_repo():
            target = args[0] if args else (kwargs.get("file") or kwargs.get("database"))
            violations.append((label, str(target)[:200], current_module[0]))
        return original(*args, **kwargs)

    return probe


builtins.open = guard("open", builtins.open)
sqlite3.connect = guard("sqlite3.connect", sqlite3.connect)
# `socket.socket` is patched by *method*, not by replacement: `ssl` does
# `class SSLSocket(socket)` at import, so rebinding the name to a function
# breaks the standard library before any of this code is reached. Constructing
# a socket is not I/O anyway -- connecting is.
socket.socket.connect = guard("socket.connect", socket.socket.connect)
socket.socket.connect_ex = guard("socket.connect_ex", socket.socket.connect_ex)
socket.create_connection = guard("socket.create_connection", socket.create_connection)

# Import the third-party stack first and *then* arm the guards. pydantic,
# pandas and pyarrow all read files when they are first imported; that is their
# business, and this test is about what this repository's own modules do.
import src  # noqa: E402
from src.config import settings as _warm_settings  # noqa: E402,F401

skipped = []

# Walked from the filesystem, not with pkgutil.walk_packages.
#
# walk_packages descends only into directories that are packages *it* can
# import, and `src/central_server/` and `src/license_service/` have no
# __init__.py -- they are namespace directories. It silently yielded neither,
# so this test reported "no import-time I/O" while covering 84 of the
# repository's 100 modules and omitting, of all things, the two that open
# databases at import. Zero violations and zero skips, for the wrong reason.
import os

names = []
for dirpath, dirnames, filenames in os.walk(SRC):
    dirnames[:] = [d for d in dirnames if d not in {{"__pycache__", "frontend"}}]
    for filename in sorted(filenames):
        if not filename.endswith(".py"):
            continue
        rel = os.path.relpath(os.path.join(dirpath, filename), SRC)
        parts = rel[:-3].split(os.sep)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            names.append("src." + ".".join(parts))
names = sorted(set(names))

armed[0] = True
for name in names:
    if name in sys.modules:
        continue
    current_module[0] = name
    try:
        importlib.import_module(name)
    except Exception as exc:  # a module whose optional dependency is absent
        skipped.append((name, "{{}}: {{}}".format(type(exc).__name__, exc)))

armed[0] = False
print(json.dumps({{"violations": violations, "skipped": skipped, "walked": names}}))
"""


def _run_probe() -> dict:
    import json

    result = subprocess.run(  # noqa: S603 - the argv is this file's own literal
        [sys.executable, "-c", _PROBE.format(repo=str(REPO_ROOT))],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, f"probe crashed:\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


#: Modules known to perform I/O at import, each against the ticket that will
#: stop it. Same ratchet rule as pyproject.toml's lint and type exemptions:
#: entries are deleted as tickets land, and nothing joins without one.
#:
#: ``src/central_server/server.py`` calls ``initialize_license_schema()`` and
#: ``initialize_data_schema()`` at module scope, so importing the hub creates
#: and opens two SQLite databases. That is the workstation's pre-VRT-12 disease
#: in the other deployable, and the cure is the same -- move it into the
#: application's lifespan. It belongs with VRT-15, which is redrawing the
#: boundary between these services anyway.
#:
#: It was not exempted before this because it was not *seen* before this: the
#: probe used ``pkgutil.walk_packages``, which skips directories without an
#: ``__init__.py``, so the entire hub and the entire licence service went
#: unwalked. The test reported zero violations across 84 of 100 modules,
#: omitting precisely the two packages that open databases at import.
KNOWN_IMPORT_TIME_IO: frozenset[str] = frozenset({"src.central_server.server"})  # VRT-15


def test_no_module_under_src_performs_io_at_import() -> None:
    """The acceptance criterion for VRT-12, stated executably.

    ``open`` is included alongside the database and socket calls because the
    licence cache read that made ``src/main.py`` untestable was a file read
    before it was ever a query.
    """
    report = _run_probe()

    violations = [v for v in report["violations"] if v[2] not in KNOWN_IMPORT_TIME_IO]
    detail = "\n".join(
        f"  {module or '<during src import>'}: {call}({target})"
        for call, target, module in violations
    )
    assert not violations, (
        "importing these modules performed I/O, which is what VRT-12 removed:\n"
        f"{detail}\n"
        "Move the work into build_container() or into a request handler. A "
        "module that does something when imported cannot be tested, cannot be "
        "configured, and cannot coexist with a second instance of itself."
    )


def test_the_probe_actually_imported_the_application() -> None:
    """Guards the test above rather than the application.

    A probe that silently imported nothing -- a renamed package, a changed
    layout, an exception swallowed too early -- would pass the assertion above
    for the worst possible reason. This asserts the modules that matter were
    genuinely reached.
    """
    report = _run_probe()
    unreachable = dict(report["skipped"])

    for critical in (
        "src.main",
        "src.interfaces.api.app",
        "src.interfaces.api.container",
        "src.interfaces.api.dependencies",
        "src.config.settings",
        "src.infrastructure.persistence.migrations",
        # The two namespace packages the old pkgutil walk silently omitted.
        # Listed by name so that losing them again fails here rather than
        # showing up as a suspiciously clean run.
        "src.central_server.server",
        "src.license_service.manager",
    ):
        assert critical not in unreachable, (
            f"{critical} could not be imported by the probe, so the I/O "
            f"assertion says nothing about it: {unreachable[critical]}"
        )


def test_the_probe_walks_every_module_including_the_namespace_packages() -> None:
    """The hole this test had, closed and pinned.

    ``pkgutil.walk_packages`` descends only into importable packages, and
    ``src/central_server/`` and ``src/license_service/`` have no ``__init__.py``.
    Sixteen modules -- the whole hub and the whole licence service -- were never
    walked, and the assertion above passed by not looking.
    """
    report = _run_probe()
    walked = set(report["walked"])

    on_disk = {
        "src." + path.relative_to(REPO_ROOT / "src").with_suffix("").as_posix().replace("/", ".")
        for path in (REPO_ROOT / "src").rglob("*.py")
        if "frontend" not in path.parts and "__pycache__" not in path.parts
    }
    on_disk = {
        name[: -len(".__init__")] if name.endswith(".__init__") else name for name in on_disk
    }

    assert on_disk - walked == set(), (
        f"modules never imported by the probe: {sorted(on_disk - walked)}"
    )

    # Named rather than counted. A threshold is a number someone lowers; these
    # are the two directories that were actually missing, and the reason they
    # were missing -- no __init__.py -- is a property they still have.
    assert "src.central_server.server" in walked
    assert "src.license_service.db_schema" in walked
