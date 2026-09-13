# src/plugin_manager/process_runner.py
"""Running one plugin as a subprocess, and keeping it alive.

A plugin is not trusted with anything the recording loop depends on (see
`src.storage.tee_sink.TeeFrameSink`), so this class's failure posture is the
opposite of `TelemetryEngine`'s: whatever the process does -- crashes, hangs,
floods stdout -- the response is "log it and maybe restart it," never
"propagate."
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ProcessRunner:
    def __init__(
        self,
        plugin_id: str,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
        restart_on_crash: bool = True,
        max_restarts_per_hour: int = 6,
    ) -> None:
        self.plugin_id = plugin_id
        self._argv = argv
        self._cwd = cwd
        self._env = env
        self._log_path = log_path
        self._restart_on_crash = restart_on_crash
        self._max_restarts_per_hour = max_restarts_per_hour

        self._process: subprocess.Popen | None = None
        self._restart_timestamps: list[float] = []
        self._stop_requested = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self.last_exit_code: int | None = None
        self.last_error: str | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def restart_count(self) -> int:
        """Restarts in the trailing hour -- what `max_restarts_per_hour` is checked against."""
        now = time.time()
        return len([t for t in self._restart_timestamps if now - t < 3600])

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_requested.clear()
        self._spawn()
        self._monitor_thread = threading.Thread(
            target=self._monitor, daemon=True, name=f"plugin-{self.plugin_id}-monitor"
        )
        self._monitor_thread.start()

    def _spawn(self) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        # SIM115: deliberately not a `with` block -- this handle must outlive
        # `_spawn()` for the life of the subprocess it's redirected into;
        # closing it here would close the pipe out from under the running
        # process. Nothing else in this class holds a reference to it, which
        # is fine: the OS reclaims it when the process (its only reader/writer)
        # exits, and a fresh one is opened on every respawn.
        log_file = self._log_path.open("ab", buffering=0)
        env = {**os.environ, **self._env}
        logger.info(f"Starting plugin '{self.plugin_id}': {' '.join(self._argv)} (cwd={self._cwd})")
        # S603: `self._argv` is built by `PluginManager` from a
        # PluginSpec.entrypoint in an operator-maintained registry.json (or a
        # venv interpreter path this codebase itself resolved), never from
        # request input.
        self._process = subprocess.Popen(  # noqa: S603
            self._argv,
            cwd=str(self._cwd),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    def _monitor(self) -> None:
        while not self._stop_requested.is_set():
            process = self._process
            if process is None:
                return
            exit_code = process.wait()
            self.last_exit_code = exit_code
            if self._stop_requested.is_set():
                logger.info(
                    f"Plugin '{self.plugin_id}' exited ({exit_code}) after a requested stop."
                )
                return

            logger.warning(f"Plugin '{self.plugin_id}' exited unexpectedly with code {exit_code}.")
            if not self._restart_on_crash:
                return

            now = time.time()
            self._restart_timestamps = [t for t in self._restart_timestamps if now - t < 3600]
            if len(self._restart_timestamps) >= self._max_restarts_per_hour:
                self.last_error = (
                    f"Exceeded {self._max_restarts_per_hour} restarts/hour; not restarting again "
                    f"automatically. Check {self._log_path} and restart the plugin manually."
                )
                logger.error(self.last_error)
                return

            self._restart_timestamps.append(now)
            backoff = min(30.0, 2.0 ** len(self._restart_timestamps))
            logger.info(f"Restarting plugin '{self.plugin_id}' in {backoff:.0f}s.")
            time.sleep(backoff)
            if self._stop_requested.is_set():
                return
            try:
                self._spawn()
            except OSError as exc:
                self.last_error = f"Failed to respawn: {exc}"
                logger.error(self.last_error)
                return

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_requested.set()
        process = self._process
        if process is None or process.poll() is not None:
            return
        logger.info(f"Stopping plugin '{self.plugin_id}' (pid {process.pid}).")
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning(
                f"Plugin '{self.plugin_id}' did not exit within {timeout:.0f}s; killing."
            )
            process.kill()
            process.wait(timeout=5.0)
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=timeout + 5.0)
