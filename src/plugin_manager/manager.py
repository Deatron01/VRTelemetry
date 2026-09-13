# src/plugin_manager/manager.py
"""PluginManager: the composition root for everything a plugin needs.

Loads registry.json, resolves each plugin's source (git clone/update, or a
local development path), validates its `plugin.json` manifest (the
"Flawless Setup" standard -- see `src.plugin_manager.manifest`), ensures its
isolated virtual environment, and owns its subprocess lifecycle. Injected
into `Container` (`src/interfaces/api/container.py`) like every other
collaborator there -- built once by `build_container()`, started and stopped
by the application's `lifespan`, never constructed at import time (see
`Container`'s module docstring for why that rule exists).

Two ways a plugin becomes known to this class: `start_all()` reads every
entry already in `registry.json` at boot (an operator-curated list); after
that, `install_plugin()`/`uninstall_plugin()` add or remove one at runtime,
on behalf of `POST /api/plugins/install` and `/uninstall`
(`src/interfaces/api/routers/plugins.py`), and persist the change back to
`registry.json` so it survives the next restart too.

A third pair, `start_plugin()`/`stop_plugin()`, never touches whether a
plugin is *installed* at all -- only whether its process is running right
now, flipping the same `enabled` flag `registry.json` already had a column
for. Behind `POST /api/plugins/start`/`/stop`, they are the pause button a
researcher wants without paying install_plugin's re-clone-from-catalog cost
just to bring a plugin back.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from src.plugin_manager.env_installer import PluginEnvironmentError, ensure_environment
from src.plugin_manager.git_ops import PluginGitError, clone_or_update
from src.plugin_manager.manifest import PluginManifest, PluginManifestError, load_manifest
from src.plugin_manager.models import PluginSource, PluginSpec, PluginStatus
from src.plugin_manager.process_runner import ProcessRunner

logger = logging.getLogger(__name__)

#: Every error one plugin's provisioning may raise. Caught per-plugin in
#: `start_all()` so one bad git remote, missing/invalid manifest, or broken
#: dependency install never stops another plugin -- or the Core Hub itself
#: -- from starting. `install_plugin()` re-raises instead: see its docstring.
PROVISIONING_ERRORS = (
    PluginGitError,
    PluginEnvironmentError,
    PluginManifestError,
    OSError,
    ValueError,
    FileNotFoundError,
)


def load_registry(registry_path: Path) -> list[PluginSpec]:
    """Parse registry.json into typed specs.

    A malformed entry is logged and skipped rather than failing the whole
    load -- one operator's typo in one plugin's block must not take every
    other plugin down with it. Returns an empty list, rather than raising, if
    the file is missing: no registry configured is a supported state (a
    workstation with zero plugins is exactly today's application).
    """
    if not registry_path.exists():
        logger.info(f"No plugin registry at {registry_path}; running with zero plugins.")
        return []

    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error(f"Could not read plugin registry {registry_path}: {exc}")
        return []

    specs: list[PluginSpec] = []
    for entry in raw.get("plugins", []):
        if not isinstance(entry, dict) or "plugin_id" not in entry:
            # "//"-prefixed keys are this file's own comment convention (see
            # plugins/registry.json) and are not plugin entries.
            continue
        try:
            specs.append(
                PluginSpec(
                    plugin_id=entry["plugin_id"],
                    source=PluginSource(entry["source"]),
                    repo_url=entry.get("repo_url"),
                    ref=entry.get("ref", "main"),
                    local_path=entry.get("local_path"),
                    requirements_file=entry.get("requirements_file", "requirements.txt"),
                    entrypoint=entry.get("entrypoint", ["python", "app.py"]),
                    env=entry.get("env", {}),
                    enabled=entry.get("enabled", True),
                    restart_on_crash=entry.get("restart_on_crash", True),
                    max_restarts_per_hour=entry.get("max_restarts_per_hour", 6),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.error(f"Skipping malformed plugin registry entry {entry!r}: {exc}")
    return specs


def _write_registry(registry_path: Path, specs: list[PluginSpec]) -> None:
    """Persist `specs` back to `registry_path`, in the shape `load_registry` reads.

    Called by `install_plugin`/`uninstall_plugin` so a plugin installed
    through the API survives a restart exactly like one an operator typed
    into registry.json by hand.

    This drops any hand-written "//..." comment entries the file had --
    registry.json's own illustrative comments (see plugins/registry.json)
    included, once anything is installed or uninstalled through the API.
    That is an accepted trade-off of making the file writable at all: a
    plugin's own `plugin.json` (validated by `src.plugin_manager.manifest`)
    is where its authoritative description now lives, so registry.json's
    comments were documentation for a human editing it by hand, not data
    anything reads.
    """
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "plugins": [
            {
                "plugin_id": spec.plugin_id,
                "source": spec.source.value,
                "repo_url": spec.repo_url,
                "ref": spec.ref,
                "local_path": spec.local_path,
                "requirements_file": spec.requirements_file,
                "entrypoint": spec.entrypoint,
                "env": spec.env,
                "enabled": spec.enabled,
                "restart_on_crash": spec.restart_on_crash,
                "max_restarts_per_hour": spec.max_restarts_per_hour,
            }
            for spec in specs
        ]
    }
    registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class PluginManager:
    """Provisions and supervises every plugin named in `registry_path`.

    Args:
        registry_path: Where registry.json lives (default suggestion in the
            plan: `<data_root>/plugins/registry.json`).
        plugins_dir: Where git-sourced plugins are cloned to (one
            subdirectory per `plugin_id`). Local-source plugins use their own
            `local_path` and are never written to by this manager.
        venvs_dir: Where each plugin's isolated virtual environment lives.
        logs_dir: Where each plugin's stdout/stderr is captured
            (`plugin_<id>.log`).
        hub_ws_url: The Event Router's own WebSocket URL, injected into every
            plugin's environment as `HUB_WS_URL` so a plugin never has to
            hardcode it.
        hub_plugin_token: If the Event Router requires a shared token
            (`EventRouter(shared_token=...)`), the same value, injected as
            `HUB_PLUGIN_TOKEN`. `None` when no token is configured.
    """

    def __init__(
        self,
        registry_path: Path,
        plugins_dir: Path,
        venvs_dir: Path,
        logs_dir: Path,
        hub_ws_url: str,
        hub_plugin_token: str | None,
    ) -> None:
        self._registry_path = registry_path
        self._plugins_dir = plugins_dir
        self._venvs_dir = venvs_dir
        self._logs_dir = logs_dir
        self._hub_ws_url = hub_ws_url
        self._hub_plugin_token = hub_plugin_token
        self._runners: dict[str, ProcessRunner] = {}
        #: Every plugin this manager knows about, installed or not, running
        #: or not -- populated by `start_all()` from registry.json and kept
        #: current by `install_plugin`/`uninstall_plugin`. What lets
        #: `status()` report "installed but not currently running" instead
        #: of only ever describing live processes.
        self._specs: dict[str, PluginSpec] = {}
        #: The manifest last read successfully for a plugin. `status()`'s
        #: name/description/version columns come from here.
        self._manifests: dict[str, PluginManifest] = {}
        #: A provisioning failure that never produced a `ProcessRunner` at
        #: all (bad git remote, invalid manifest, failed pip install) has
        #: nowhere else to be recorded -- `ProcessRunner.last_error` only
        #: exists for a plugin that got as far as being spawned.
        self._start_errors: dict[str, str] = {}

    def start_all(self) -> None:
        """Provision and start every enabled plugin from registry.json. Never raises.

        Called from the application's `lifespan`, alongside the sync
        scheduler and heartbeat sender, and held to the same rule stated
        there: a workstation must come up even when a plugin's git remote is
        unreachable, its manifest is invalid, or its dependencies fail to
        install. Each plugin's provisioning is independently guarded so one
        broken plugin does not cost the others -- or the Core Hub itself
        failing to boot.
        """
        for spec in load_registry(self._registry_path):
            self._specs[spec.plugin_id] = spec
            if not spec.enabled:
                logger.info(f"Plugin '{spec.plugin_id}' is disabled in the registry; not starting.")
                continue
            self._try_start(spec)

    def _try_start(self, spec: PluginSpec) -> None:
        self._start_errors.pop(spec.plugin_id, None)
        try:
            self._start_one(spec)
        except PROVISIONING_ERRORS as exc:
            message = str(exc)
            self._start_errors[spec.plugin_id] = message
            logger.error(f"Plugin '{spec.plugin_id}' could not be started: {message}")

    def _resolve_plugin_dir(self, spec: PluginSpec) -> Path:
        if spec.source is PluginSource.GIT:
            if not spec.repo_url:
                raise ValueError(f"Plugin '{spec.plugin_id}' has source=git but no repo_url.")
            plugin_dir = self._plugins_dir / spec.plugin_id
            clone_or_update(spec.repo_url, spec.ref, plugin_dir)
            return plugin_dir

        if not spec.local_path:
            raise ValueError(f"Plugin '{spec.plugin_id}' has source=local but no local_path.")
        plugin_dir = Path(spec.local_path)
        if not plugin_dir.is_dir():
            raise FileNotFoundError(
                f"Plugin '{spec.plugin_id}' local_path does not exist: {plugin_dir}"
            )
        return plugin_dir

    def _start_one(self, spec: PluginSpec) -> None:
        plugin_dir = self._resolve_plugin_dir(spec)

        # "Flawless Setup": every plugin, git- or local-sourced, must carry a
        # valid plugin.json before it is ever cloned into a venv or spawned.
        # The manifest -- not registry.json's own entrypoint/requirements_file
        # fields, which predate it -- is the authority on how to run it: a
        # plugin's own repository is what should be able to change its
        # entrypoint, not an operator's local registry.json edit.
        manifest = load_manifest(plugin_dir)
        if manifest.plugin_id != spec.plugin_id:
            raise PluginManifestError(
                f"registry.json plugin_id '{spec.plugin_id}' does not match plugin.json's "
                f"plugin_id '{manifest.plugin_id}' at {plugin_dir}."
            )
        self._manifests[spec.plugin_id] = manifest

        venv_dir = self._venvs_dir / spec.plugin_id
        python = ensure_environment(plugin_dir, venv_dir, manifest.requirements_file)

        argv = [str(python) if part == "python" else part for part in manifest.entrypoint]
        env = {**spec.env, "PLUGIN_ID": spec.plugin_id, "HUB_WS_URL": self._hub_ws_url}
        if self._hub_plugin_token:
            env["HUB_PLUGIN_TOKEN"] = self._hub_plugin_token

        runner = ProcessRunner(
            plugin_id=spec.plugin_id,
            argv=argv,
            cwd=plugin_dir,
            env=env,
            log_path=self._logs_dir / f"plugin_{spec.plugin_id}.log",
            restart_on_crash=spec.restart_on_crash,
            max_restarts_per_hour=spec.max_restarts_per_hour,
        )
        runner.start()
        self._runners[spec.plugin_id] = runner

    def install_plugin(
        self,
        *,
        plugin_id: str,
        repo_url: str,
        ref: str = "main",
        env: dict[str, str] | None = None,
    ) -> PluginStatus:
        """Register a git-sourced plugin, persist it, and start it now.

        This is `POST /api/plugins/install`'s implementation: a researcher
        clicking "Install" in the catalog UI must not have to restart the
        workstation for it to take effect, and the choice must survive one --
        neither of which `start_all()` alone provides, since it only ever
        runs once, at boot. `entrypoint` and `requirements_file` are not
        parameters here: they come from the plugin's own `plugin.json`,
        cloned and validated as part of this call (see `_start_one`) --
        exactly the point of the "Flawless Setup" standard, that a plugin's
        repository is self-describing rather than needing an operator to
        already know its internals before installing it.

        An existing installation of the same `plugin_id` is stopped and
        replaced first -- this is also how "reinstall" or "move to a new
        ref" work, there being no meaningful difference between those and a
        fresh install from this method's point of view.

        Returns:
            The freshly (re)started plugin's status.

        Raises:
            PluginGitError, PluginEnvironmentError, PluginManifestError,
            OSError, ValueError, FileNotFoundError: provisioning failed.
            Unlike `start_all()`, this is **not** swallowed: the researcher
            who clicked "Install" needs to see why, in the body of the
            error `POST /api/plugins/install` returns -- silently recording
            "installed" for a plugin that never actually started would be
            worse than the 4xx/5xx this raises into.
        """
        existing_runner = self._runners.pop(plugin_id, None)
        if existing_runner is not None:
            existing_runner.stop()

        spec = PluginSpec(
            plugin_id=plugin_id,
            source=PluginSource.GIT,
            repo_url=repo_url,
            ref=ref,
            env=env or {},
            enabled=True,
        )
        self._specs[plugin_id] = spec
        self._persist_registry()

        self._start_errors.pop(plugin_id, None)
        try:
            self._start_one(spec)
        except PROVISIONING_ERRORS as exc:
            self._start_errors[plugin_id] = str(exc)
            raise
        return self._status_for(plugin_id)

    def uninstall_plugin(self, plugin_id: str) -> bool:
        """Stop the plugin if running, and remove it from the registry.

        Returns:
            True if the plugin was known (installed) before this call, False
            if there was nothing to uninstall -- the caller
            (`POST /api/plugins/uninstall`) turns a False into a 404.
        """
        runner = self._runners.pop(plugin_id, None)
        if runner is not None:
            runner.stop()
        self._manifests.pop(plugin_id, None)
        self._start_errors.pop(plugin_id, None)
        existed = self._specs.pop(plugin_id, None) is not None
        if existed:
            self._persist_registry()
        return existed

    def stop_plugin(self, plugin_id: str) -> PluginStatus | None:
        """Stop an installed plugin's process without uninstalling it.

        Distinct from `uninstall_plugin` on purpose: this keeps the git
        checkout, the isolated venv, and the `registry.json` entry itself in
        place (with `enabled` flipped to False) so `start_plugin` can bring
        it back without re-cloning or reinstalling dependencies -- the
        difference between a pause button and a delete button.

        Returns:
            The plugin's fresh status (now `running: False`, `enabled:
            False`), or `None` if `plugin_id` is not installed at all -- the
            caller (`POST /api/plugins/stop`) turns that into a 404.
        """
        spec = self._specs.get(plugin_id)
        if spec is None:
            return None

        runner = self._runners.pop(plugin_id, None)
        if runner is not None:
            runner.stop()

        self._specs[plugin_id] = dataclasses.replace(spec, enabled=False)
        self._start_errors.pop(plugin_id, None)
        self._persist_registry()
        return self._status_for(plugin_id)

    def start_plugin(self, plugin_id: str) -> PluginStatus | None:
        """(Re)start an installed plugin that is currently stopped.

        The counterpart to `stop_plugin`: flips `enabled` back to True and
        persists it, then provisions a fresh process only if one isn't
        already running -- a plugin that's already up is left alone rather
        than being restarted for no reason. Provisioning here reuses
        `_start_one`, the same path `start_all()` and `install_plugin()`
        use, so a plugin whose git checkout or venv went stale between stop
        and start is repaired (re-cloned/re-`pip install`ed) exactly as it
        would be on a fresh install, without needing the catalog's
        `repo_url` again.

        Returns:
            The plugin's fresh status, or `None` if `plugin_id` is not
            installed at all -- the caller (`POST /api/plugins/start`) turns
            that into a 404, exactly like `uninstall_plugin`'s `False`.

        Raises:
            PluginGitError, PluginEnvironmentError, PluginManifestError,
            OSError, ValueError, FileNotFoundError: provisioning failed.
            Not swallowed, for the same reason `install_plugin` doesn't
            swallow it: the researcher who clicked "Start" needs to see why
            in the response, not have it silently stay stopped.
        """
        spec = self._specs.get(plugin_id)
        if spec is None:
            return None

        spec = dataclasses.replace(spec, enabled=True)
        self._specs[plugin_id] = spec
        self._persist_registry()

        runner = self._runners.get(plugin_id)
        if runner is not None and runner.is_running:
            return self._status_for(plugin_id)

        self._start_errors.pop(plugin_id, None)
        try:
            self._start_one(spec)
        except PROVISIONING_ERRORS as exc:
            self._start_errors[plugin_id] = str(exc)
            raise
        return self._status_for(plugin_id)

    def _persist_registry(self) -> None:
        _write_registry(self._registry_path, list(self._specs.values()))

    def stop_all(self) -> None:
        for runner in self._runners.values():
            runner.stop()
        self._runners.clear()

    def _status_for(self, plugin_id: str) -> PluginStatus:
        spec = self._specs.get(plugin_id)
        runner = self._runners.get(plugin_id)
        manifest = self._manifests.get(plugin_id)
        return PluginStatus(
            plugin_id=plugin_id,
            installed=spec is not None,
            enabled=bool(spec.enabled) if spec is not None else False,
            running=bool(runner.is_running) if runner is not None else False,
            pid=runner.pid if runner is not None else None,
            restarts=runner.restart_count if runner is not None else 0,
            last_exit_code=runner.last_exit_code if runner is not None else None,
            last_error=(runner.last_error if runner is not None else None)
            or self._start_errors.get(plugin_id),
            name=manifest.name if manifest is not None else None,
            description=manifest.description if manifest is not None else None,
            version=manifest.version if manifest is not None else None,
        )

    def status(self) -> list[PluginStatus]:
        """A snapshot of every installed plugin -- running or not.

        Iterates `self._specs` (everything registered), not `self._runners`
        (only what is currently a live process): a disabled plugin, or one
        whose provisioning failed, still needs to be visible to
        `GET /api/plugins/status` rather than silently missing from the list.
        """
        return [self._status_for(plugin_id) for plugin_id in self._specs]
