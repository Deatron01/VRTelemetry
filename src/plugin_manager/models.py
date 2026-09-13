# src/plugin_manager/models.py
"""Typed shape of registry.json and one plugin's runtime status."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PluginSource(str, Enum):
    GIT = "git"
    LOCAL = "local"


@dataclass(frozen=True)
class PluginSpec:
    """One entry in registry.json -- what `PluginManager` needs to run a plugin.

    A plugin is an independent process the Core Hub does not trust with
    anything the recording loop depends on: it subscribes to
    `/ws/hub/telemetry` like any other client, and recording continues
    identically whether it is running, crashed, or was never started (see
    `src.storage.tee_sink.TeeFrameSink`).
    """

    plugin_id: str
    source: PluginSource
    #: git clone URL. Required when source is GIT, ignored otherwise.
    repo_url: str | None = None
    #: git ref (branch, tag, or commit SHA) to check out after clone/pull.
    ref: str = "main"
    #: For source LOCAL: an existing directory on disk -- local plugin
    #: development, or a plugin vendored directly into this repository (e.g.
    #: under `plugins/`). For source GIT: unused; the manager derives the
    #: checkout path from `plugins_dir` / `plugin_id`.
    local_path: str | None = None
    #: Relative to the plugin's own directory.
    requirements_file: str = "requirements.txt"
    #: Argv to launch the plugin. The literal token "python" is resolved to
    #: the plugin's own isolated venv interpreter (never whatever "python"
    #: means on the operator's PATH) -- see `PluginManager._start_one`.
    entrypoint: list[str] = field(default_factory=lambda: ["python", "app.py"])
    #: Extra environment variables. PLUGIN_ID and HUB_WS_URL (and
    #: HUB_PLUGIN_TOKEN, if configured) are always injected on top of these
    #: -- see `PluginManager._start_one`.
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    #: Restart on unexpected exit. A plugin that exits 0 deliberately (a
    #: one-shot batch job, not a subscriber) should set this False.
    restart_on_crash: bool = True
    max_restarts_per_hour: int = 6


@dataclass
class PluginStatus:
    """A snapshot for a status endpoint or an operator log line. Never used
    to make a decision inside the recording path.

    Covers a plugin whether or not it is currently running: `installed` is
    true for anything registered with `PluginManager` (via `registry.json`
    at boot, or `install_plugin()` afterwards), independent of `running`,
    which reflects the actual OS process. A plugin can be installed and not
    running (disabled in the registry, or its process crashed past
    `max_restarts_per_hour`) -- that distinction is what
    `GET /api/plugins/status` needs to show a researcher "installed but not
    started" rather than making it look identical to "not installed".
    """

    plugin_id: str
    installed: bool
    enabled: bool
    running: bool
    pid: int | None
    restarts: int
    last_exit_code: int | None
    last_error: str | None
    #: From the plugin's own `plugin.json`, when it was readable at the last
    #: (re)start attempt. `None` for a registered-but-never-started plugin,
    #: or one whose manifest failed validation -- see `last_error` for why.
    name: str | None = None
    description: str | None = None
    version: str | None = None
