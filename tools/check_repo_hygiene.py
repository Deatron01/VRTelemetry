#!/usr/bin/env python3
"""Fail the build if the repository is tracking something it must not track.

This exists because of a real incident: 672 files of recorded research-session
data -- including subject microphone audio -- reached this repository's public
git history, alongside a 100 MB archive, a 32 MB APK and 5,371 vendored
``node_modules`` files. A ``.gitignore`` prevents that only for as long as
nobody uses ``git add -f`` or adds a path the ignore rules do not anticipate.
This check is the mechanical backstop: it inspects what git is *actually*
tracking rather than what the ignore file intends.

Run locally::

    python tools/check_repo_hygiene.py

Exit codes:
    0  repository is clean
    1  forbidden tracked paths found, or a required path is missing
    2  the check could not run (not a git repository, git unavailable)

Wired into CI as the first job so a violation fails fast and cheaply, and into
``.pre-commit-config.yaml`` so it fails on the developer's machine first.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #

#: Categories of path that must never be tracked. Each entry pairs a regex
#: matched against the repository-relative POSIX path with the reason shown to
#: whoever trips it -- an error message that does not explain itself just gets
#: worked around.
FORBIDDEN: tuple[tuple[str, str], ...] = (
    (
        r"(^|/)Sessions/|(^|/)Logs/|(^|/)AppData/|(^|/)CentralServer/|(^|/)LicenseServer/",
        "Runtime data root. Recorded sessions contain special-category personal "
        "data and must never enter git history.",
    ),
    (
        r"\.(wav|mp3|m4a|flac)$",
        "Audio file. Subject microphone recordings were previously leaked this way.",
    ),
    (
        r"\.(parquet|db|sqlite3|db-wal|db-shm)$",
        "Recorded telemetry or a metadata/licence database. Contains subject data.",
    ),
    (
        r"(^|/)node_modules/",
        "Vendored npm dependencies. Reproduced from package-lock.json; committing "
        "them once cost this repository 400 MB and 94.6% of its tracked files.",
    ),
    (
        r"\.(rar|zip|7z|tar\.gz|tgz|apk|exe|msi|dmg|AppImage)$",
        "Binary distributable or archive. Publish these as release assets, not as git objects.",
    ),
    (
        r"(^|/)(venv|\.venv|env)/",
        "Virtual environment. Reproduced from pyproject.toml.",
    ),
    (
        r"(^|/)__pycache__/|\.py[cod]$",
        "Python bytecode cache.",
    ),
    (
        r"\.(pem|key)$",
        "TLS private key or certificate. A leaked hub key lets anyone on the LAN "
        "impersonate the hub and receive participant data (GDPR-01).",
    ),
    (
        r"(^|/)\.env$|(^|/)\.env\.(?!example)",
        "Environment file. May contain credentials; commit .env.example instead.",
    ),
)

#: Paths that must stay tracked, with the reason each one matters. A build input
#: silently excluded by an over-broad ignore rule is the mirror image of the
#: problem above, and is exactly how ``npm run package`` came to be unbuildable
#: on every machine except one.
REQUIRED: tuple[tuple[str, str], ...] = (
    (
        "build/backend.spec",
        "PyInstaller build input required by `npm run build:backend`. Previously "
        "excluded by a blanket `build/` ignore rule.",
    ),
    (
        "build/make-installer-license.js",
        "Generates the installer's licence page from LICENSE + DISCLAIMER.md; "
        "`npm run package` fails without it.",
    ),
    (
        "LICENSE",
        "The terms the source is published under. Bundled into every installer.",
    ),
    (
        "DISCLAIMER.md",
        "Research-use-only / not-a-medical-device statement. Part of the licence, "
        "shown on the installer's licence page and bundled with every build.",
    ),
)

#: Tracked-file count above which the repository is considered to have drifted.
#: Not a hard architectural limit -- a tripwire. Raise it deliberately in a
#: commit that explains why, never to silence a failure.
#:
#: 400 -> 410 on 12 Sep 2026. The 401st file is
#: tests/unit/test_derived_metrics.py, the first coverage
#: compute_binocular_focal_distance has ever had (it was silently returning its
#: near-parallel fallback for every frame of every HTC session). The headroom
#: is so the next legitimate test file does not block a commit and train
#: everyone to bump this reflexively, which is what the note above is guarding
#: against. It still catches what it was built for: node_modules or a session
#: dump arrives in the hundreds, not in ones.
#:
#: 410 -> 440 on 13 Sep 2026. 30 files arrived in one commit: the VR Telemetry
#: Hub plugin architecture -- `src/plugin_manager/` (the composition root and
#: its manifest/env/git-ops/process-runner collaborators), the Core Hub's
#: `event_router.py`/`tee_sink.py`/`broadcast_sink.py` split, two reference
#: plugins under `plugins/` (each with its own README/plugin.json/requirements.txt),
#: the Central Server's `plugin_catalog.py`/`.json`, the workstation's
#: `plugins` router/schemas, and the frontend's `Plugins.tsx` panel. Reviewed
#: and deliberate, not vendored dependencies or session data arriving in
#: bulk -- but still exactly the shape this check exists to make someone look
#: at rather than wave through silently. Headroom is deliberately smaller than
#: the jump itself, same reasoning as the 410 bump above.
#:
#: 440 -> 480 on 15 Oct 2026. Two reviewed batches for v1.1.0: 14 files of
#: biosensor ingest / desktop mirror / synced session video (routers, schemas,
#: repository, sidecar writer, two frontend components, three test modules),
#: and the hub installer (frozen-hub CLI and spec, NSIS script, the certificate
#: tool moved into the package, their tests, and the design note). Source and
#: tests only -- the installers themselves go to release assets, never here.
MAX_TRACKED_FILES = 480


# --------------------------------------------------------------------------- #
# Implementation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Violation:
    """A single tracked path that policy forbids."""

    path: str
    reason: str


def tracked_files() -> list[str]:
    """Return every path git currently tracks, as repository-relative POSIX paths.

    Raises:
        SystemExit: if git is unavailable or this is not a repository. The check
            refuses to pass silently when it could not actually inspect anything.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError:
        sys.stderr.write("repo-hygiene: git executable not found\n")
        raise SystemExit(2) from None
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"repo-hygiene: `git ls-files` failed: {exc.stderr.strip()}\n")
        raise SystemExit(2) from exc

    return [entry for entry in completed.stdout.split("\0") if entry]


def find_violations(paths: list[str]) -> list[Violation]:
    """Match tracked paths against the forbidden-path policy.

    Args:
        paths: Repository-relative paths, as returned by :func:`tracked_files`.

    Returns:
        One violation per offending path, in the order the paths were given.
        A path matching several rules is reported once, against the first rule
        it matches, so the output stays proportional to the problem.
    """
    compiled = [(re.compile(pattern), reason) for pattern, reason in FORBIDDEN]
    violations: list[Violation] = []
    for path in paths:
        for pattern, reason in compiled:
            if pattern.search(path):
                violations.append(Violation(path=path, reason=reason))
                break
    return violations


def find_missing(paths: list[str]) -> list[Violation]:
    """Return required build inputs that are absent from the tracked set."""
    tracked = set(paths)
    return [Violation(path=path, reason=reason) for path, reason in REQUIRED if path not in tracked]


def _report(title: str, violations: list[Violation]) -> None:
    """Print a grouped, actionable report for one class of failure."""
    sys.stderr.write(f"\n{title}\n")
    by_reason: dict[str, list[str]] = {}
    for violation in violations:
        by_reason.setdefault(violation.reason, []).append(violation.path)

    for reason, group in by_reason.items():
        sys.stderr.write(f"\n  {reason}\n")
        for path in sorted(group)[:10]:
            sys.stderr.write(f"    {path}\n")
        if len(group) > 10:
            sys.stderr.write(f"    ... and {len(group) - 10} more\n")


def main() -> int:
    """Run the hygiene check. Returns the process exit code."""
    paths = tracked_files()

    violations = find_violations(paths)
    missing = find_missing(paths)
    over_budget = len(paths) > MAX_TRACKED_FILES

    if not (violations or missing or over_budget):
        print(f"repo-hygiene: OK ({len(paths)} tracked files)")
        return 0

    if violations:
        _report(
            f"repo-hygiene: {len(violations)} forbidden path(s) are tracked.",
            violations,
        )
        sys.stderr.write(
            "\n  Fix: `git rm --cached <path>` and confirm .gitignore covers it.\n"
            "  If personal data has already been pushed, removing it from HEAD is\n"
            "  NOT sufficient -- the blob stays reachable. Escalate before pushing.\n"
        )

    if missing:
        _report("repo-hygiene: required build input(s) are not tracked.", missing)
        sys.stderr.write("\n  Fix: `git add -f <path>` and check `git check-ignore -v <path>`.\n")

    if over_budget:
        sys.stderr.write(
            f"\nrepo-hygiene: {len(paths)} tracked files exceeds the budget of "
            f"{MAX_TRACKED_FILES}.\n"
            "  Something bulk-entered the repository. Review before raising the limit.\n"
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
