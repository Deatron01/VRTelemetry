# src/version.py
"""One place the application's version is decided.

``"1.0.0"`` was a literal in three separate default arguments --
``HeartbeatSender.app_version``, ``UsageTracker.app_version`` and a column
written by ``DatabaseManager`` -- which is three places to forget when it
changes, and the symptom of forgetting is a hub dashboard reporting a version
the workstation stopped being months ago.

Resolved from installed package metadata so a real install reports what is
actually installed, with a literal fallback for the two cases where metadata is
absent: a source checkout that was never ``pip install``-ed, and a PyInstaller
bundle, which does not carry ``.dist-info`` unless it is told to.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

#: What to report when package metadata is unavailable. Kept in step with
#: ``pyproject.toml``'s ``version`` by hand; there is no way to read that file
#: from a frozen bundle, which is the case this fallback exists for.
FALLBACK_VERSION = "1.1.3"

try:
    APP_VERSION: str = version("vrtelemetry")
except PackageNotFoundError:  # pragma: no cover - depends on how this is installed
    APP_VERSION = FALLBACK_VERSION
