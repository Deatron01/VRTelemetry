# src/plugin_manager/git_ops.py
"""Cloning and updating plugin repositories.

Shells out to the `git` binary rather than a library: every operation here
is one an operator could type themselves, and a failed clone raises git's own
stderr -- more useful to debug than a wrapped library exception.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class PluginGitError(RuntimeError):
    """A git operation failed. The message is git's own stderr, truncated."""


def _run_git(args: list[str], cwd: Path | None = None, timeout: float = 120.0) -> str:
    try:
        # S603/S607: `args` comes from this module's own callers (fixed git
        # subcommands plus a repo_url/ref from an operator-maintained
        # registry.json -- see PluginSpec), never from request input, and
        # "git" is intentionally resolved from PATH rather than hardcoded to
        # one install location (see the FileNotFoundError message below).
        result = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PluginGitError("git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PluginGitError(f"git {' '.join(args)} timed out after {timeout:.0f}s.") from exc

    if result.returncode != 0:
        raise PluginGitError(f"git {' '.join(args)} failed: {result.stderr.strip()[:2000]}")
    return result.stdout


def _looks_like_commit_sha(ref: str) -> bool:
    return 7 <= len(ref) <= 40 and all(c in "0123456789abcdefABCDEF" for c in ref)


def clone_or_update(repo_url: str, ref: str, dest: Path) -> None:
    """Ensure `dest` holds a checkout of `repo_url` at `ref`.

    Idempotent: a fresh clone the first time this is called for `dest`, a
    fetch + hard reset to the resolved ref on every call after. The hard
    reset is deliberate -- a plugin repository is not somewhere an operator's
    local edits should survive an update. Local plugin development uses
    `PluginSource.LOCAL` instead, which this function never touches.

    Raises:
        PluginGitError: any git invocation failed. Callers (`PluginManager`)
            log this and skip the plugin -- one plugin's bad remote must
            never stop the others, or the Core Hub, from starting.
    """
    if (dest / ".git").exists():
        logger.info(f"Updating plugin checkout at {dest} to {ref!r}.")
        _run_git(["fetch", "--all", "--tags"], cwd=dest)
        target = ref if _looks_like_commit_sha(ref) else f"origin/{ref}"
        _run_git(["reset", "--hard", target], cwd=dest)
        _run_git(["clean", "-fdx"], cwd=dest)
    else:
        logger.info(f"Cloning plugin {repo_url!r} into {dest}.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if _looks_like_commit_sha(ref):
            # A shallow branch clone can't check out an arbitrary commit
            # that isn't a branch tip, so a pinned SHA gets a full clone
            # followed by an explicit checkout.
            _run_git(["clone", repo_url, str(dest)])
            _run_git(["checkout", ref], cwd=dest)
        else:
            _run_git(["clone", "--branch", ref, "--single-branch", repo_url, str(dest)])
