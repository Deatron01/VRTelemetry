# src/plugin_manager/env_installer.py
"""One isolated virtual environment per plugin.

Each plugin gets its own venv under `PluginManager`'s `venvs_dir` rather than
installing into the Core Hub's own interpreter: a plugin author's
`requirements.txt` (an old numpy, a conflicting pydantic major version, a
different fastapi) must never be able to break the recording process by
colliding with what it depends on. This is the dependency-safety half of
requirement 2 in the plan; `git_ops.py` is the source-control half.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class PluginEnvironmentError(RuntimeError):
    """Creating the venv, or installing its requirements, failed."""


def venv_python(venv_dir: Path) -> Path:
    """Path to the interpreter inside `venv_dir`, Windows or POSIX."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def ensure_environment(
    plugin_dir: Path,
    venv_dir: Path,
    requirements_file: str,
    timeout: float = 600.0,
) -> Path:
    """Create `venv_dir` if needed and install `requirements_file` into it.

    Reinstall is skipped when a hash of the requirements file matches a
    marker left by the last successful install (`.requirements.sha256` inside
    the venv) -- a plugin manager that shells out to pip on every restart of
    a long-running study is not one an operator can trust not to stall a
    session on a flaky package index.

    Returns:
        The venv's interpreter path, ready to be the first argv token of the
        plugin's entrypoint.

    Raises:
        PluginEnvironmentError: venv creation or `pip install` failed. The
            caller (`PluginManager`) treats this exactly like a plugin that
            failed to start -- logged and skipped, never raised into the
            application's boot sequence.
    """
    python = venv_python(venv_dir)
    requirements_path = plugin_dir / requirements_file

    if not python.exists():
        logger.info(f"Creating virtual environment for plugin at {venv_dir}.")
        _run([sys.executable, "-m", "venv", str(venv_dir)], timeout=timeout)

    if not requirements_path.exists():
        logger.info(
            f"No {requirements_file} for plugin at {plugin_dir}; skipping dependency install."
        )
        return python

    digest = hashlib.sha256(requirements_path.read_bytes()).hexdigest()
    marker = venv_dir / ".requirements.sha256"
    if marker.exists() and marker.read_text().strip() == digest:
        logger.debug(
            f"Plugin dependencies at {venv_dir} already match {requirements_file}; skipping install."
        )
        return python

    logger.info(f"Installing {requirements_path} into {venv_dir} (first run can take a while).")
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip"], timeout=timeout)
    _run([str(python), "-m", "pip", "install", "-r", str(requirements_path)], timeout=timeout)
    marker.write_text(digest)
    return python


def _run(args: list[str], timeout: float) -> None:
    try:
        # S603: `args` is always this module's own construction (venv/pip
        # invocations against a plugin's own requirements.txt path), never
        # request input.
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    except subprocess.TimeoutExpired as exc:
        raise PluginEnvironmentError(f"{' '.join(args)} timed out after {timeout:.0f}s.") from exc
    if result.returncode != 0:
        raise PluginEnvironmentError(f"{' '.join(args)} failed:\n{result.stderr.strip()[-4000:]}")
