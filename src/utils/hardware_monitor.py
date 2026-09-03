# src/utils/hardware_monitor.py

import contextlib
import logging
import subprocess
import threading
import time

import psutil

logger = logging.getLogger(__name__)

#: What "the GPU probe did not answer" looks like (VRT-13). ``OSError`` is
#: nvidia-smi not being on PATH at all; ``SubprocessError`` covers the timeout
#: and the non-zero exit; ``ValueError``/``IndexError`` are the output being
#: empty or not a number, which happens while a driver is restarting.
#:
#: Anything else -- a typo in the argument list, say -- is a defect here and is
#: left to travel, where before it was indistinguishable from "no GPU".
_GPU_PROBE_FAULTS = (OSError, subprocess.SubprocessError, ValueError, IndexError)


class HardwareMonitor:
    """
    Decoupled low-frequency hardware metric poller.
    Operates on an independent OS thread to continuously update CPU/Audio vectors
    without interrupting the OpenXR sub-millisecond precision loops.
    """

    def __init__(self, target_hz: int = 10):
        self.target_hz = target_hz
        self.sleep_interval = 1.0 / self.target_hz
        self.is_running = False

        self.cpu_usage: float = 0.0
        self.voice_db: float = -60.0
        self.gpu_usage: float = -1.0  # -1.0 = unavailable, never "0% load"

        self._gpu_available: bool | None = None
        self._last_gpu_poll_ts = 0.0
        self._thread: threading.Thread | None = None

        #: Ticks the poll loop failed outright (VRT-13). See :meth:`_poll_loop`
        #: for why the loop survives them; this is what makes it visible that it
        #: had to.
        self.poll_faults = 0

    def start(self) -> None:
        """Initializes the background daemon for system polling."""
        self.is_running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="HardwareMonitorDaemon"
        )
        self._thread.start()
        logger.info(f"Hardware subsystem monitor booted at {self.target_hz} Hz.")

    def _gpu_supported(self) -> bool:
        if self._gpu_available is None:
            try:
                subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader"],
                    capture_output=True,
                    timeout=2,
                    check=True,
                )
                self._gpu_available = True
            except _GPU_PROBE_FAULTS:
                self._gpu_available = False
                logger.info(
                    "nvidia-smi not available — gpu_utilization will be recorded as -1.0 (unavailable)."
                )
        return self._gpu_available

    def _poll_loop(self) -> None:
        psutil.cpu_percent(interval=None)
        while self.is_running:
            try:
                self.cpu_usage = float(psutil.cpu_percent(interval=None)) / 100.0
                self.voice_db = -60.0

                # nvidia-smi is a subprocess spawn — too expensive to run at 10Hz, so throttle to 1Hz
                now = time.time()
                if self._gpu_supported() and (now - self._last_gpu_poll_ts) >= 1.0:
                    self._last_gpu_poll_ts = now
                    # Suppressed deliberately and silently: this runs once a
                    # second for the length of a session, so logging a driver
                    # hiccup here would bury the log it shares with the
                    # acquisition loop. Keeping the last known value is the
                    # honest reading -- utilisation did not become unknown, we
                    # just missed one sample of it.
                    with contextlib.suppress(*_GPU_PROBE_FAULTS):
                        result = subprocess.run(
                            [
                                "nvidia-smi",
                                "--query-gpu=utilization.gpu",
                                "--format=csv,noheader,nounits",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=1,
                        )
                        self.gpu_usage = float(result.stdout.strip().splitlines()[0]) / 100.0

            except Exception as e:  # noqa: BLE001 - thread top level: the monitor must outlive one bad tick
                # This thread supplies cpu/gpu/voice into every frame. If it
                # dies, those columns silently freeze at their last value for
                # the rest of the session and nothing says so. Surviving a bad
                # tick is worth more than the exception, but the fault is now
                # counted, so a session that lost the monitor is visible.
                self.poll_faults += 1
                logger.debug(f"Hardware poll misfire ({self.poll_faults} so far): {e}")

            time.sleep(self.sleep_interval)

    def stop(self) -> None:
        """Gracefully halts the hardware thread."""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
