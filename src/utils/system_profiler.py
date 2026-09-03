# src/utils/system_profiler.py

import getpass
import logging
import platform
import socket
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def collect_system_profile() -> dict[str, Any]:
    """Snapshot the host machine and environment at session start.

    This is part of the same consented data-collection scope as biometric
    telemetry (see GDPRConsentError) — it travels inside session metadata,
    not as a separate uncontrolled collection channel.

    **This function never raises** (VRT-13). It is a probe: every field is
    optional, a missing one costs a line of context in a research dataset, and
    nothing here is worth failing a recording over. That contract is stated
    because it is what lets every caller invoke it bare — and because the two
    callers previously disagreed about it, one wrapping it in ``try/except`` and
    the other not, which is the state in which a real fault is handled by
    neither.

    The tolerance is bounded: each probe catches the failures that probe can
    actually produce, so a genuine defect in this module still surfaces.

    Returns:
        Whatever could be collected. Keys are absent or "Unknown" rather than
        the whole profile being lost.
    """
    profile: dict[str, Any] = {}

    # platform and socket read the OS's own identity. On a locked-down or
    # containerised host these can fail (no hostname resolver, no /proc); each
    # is independent, so one failing must not cost the others.
    for key, probe in (
        ("os_name", platform.system),
        ("os_version", platform.version),
        ("os_release", platform.release),
        ("architecture", platform.machine),
        ("hostname", socket.gethostname),
        ("python_version", platform.python_version),
        ("cpu_name", lambda: platform.processor() or "Unknown"),
        ("os_user", getpass.getuser),
    ):
        try:
            profile[key] = probe()
        except (OSError, KeyError) as e:
            # OSError: the OS refused to answer. KeyError: getpass.getuser()
            # raises it when no passwd entry and no LOGNAME/USER/USERNAME exist,
            # which is the normal state inside a container.
            logger.debug(f"System profile field '{key}' unavailable: {e}")
            profile[key] = "Unknown"

    if PSUTIL_AVAILABLE:
        try:
            vm = psutil.virtual_memory()
            profile["total_ram_gb"] = round(vm.total / (1024**3), 2)
            profile["cpu_cores_logical"] = psutil.cpu_count(logical=True)
            profile["cpu_cores_physical"] = psutil.cpu_count(logical=False)
            profile["cpu_freq_mhz"] = getattr(psutil.cpu_freq(), "max", None)

            disk = psutil.disk_usage("/")
            profile["disk_total_gb"] = round(disk.total / (1024**3), 2)
            profile["disk_free_gb"] = round(disk.free / (1024**3), 2)

            battery = psutil.sensors_battery()
            if battery:
                profile["host_battery_pct"] = battery.percent
                profile["host_on_ac_power"] = battery.power_plugged
        except (OSError, AttributeError, psutil.Error) as e:
            # psutil.Error covers its own family (AccessDenied, NoSuchProcess).
            # AttributeError is here on purpose: psutil omits sensors_battery and
            # cpu_freq entirely on platforms that cannot report them, so the
            # attribute genuinely does not exist rather than failing when called.
            logger.debug(f"psutil system profiling partial failure: {e}")
    else:
        logger.warning("psutil not available — system profile will be incomplete.")

    profile["gpu_info"] = _collect_gpu_info()

    return profile


def _collect_gpu_info() -> str:
    """
    Best-effort GPU identification. Full GPU driver/VRAM detail typically
    requires vendor-specific APIs (nvidia-smi, DXGI, etc.) which we don't
    want as hard dependencies — this stays a soft, non-blocking probe.
    """
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip() and "Name" not in l]
            return ", ".join(lines) if lines else "Unknown"
        elif platform.system() == "Linux":
            result = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            gpu_lines = [
                l for l in result.stdout.splitlines() if "VGA" in l or "3D controller" in l
            ]
            return "; ".join(gpu_lines) if gpu_lines else "Unknown"
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip()[:500] if result.stdout else "Unknown"
    except (OSError, subprocess.SubprocessError) as e:
        # The vendor tool is absent (OSError) or misbehaved -- timed out, or
        # exited non-zero (SubprocessError). Both mean "no GPU name available",
        # which is a legitimate answer on a machine without a discrete GPU.
        logger.debug(f"GPU info collection failed: {e}")
    return "Unknown"


def collect_runtime_snapshot() -> dict[str, Any]:
    """
    Lightweight, cheap-to-call snapshot for periodic sampling during an active
    session (CPU/RAM load over time), distinct from the one-time static profile
    above. Called repeatedly by HardwareMonitor without the heavier GPU/disk probes.
    """
    if not PSUTIL_AVAILABLE:
        return {}
    try:
        return {
            "cpu_load_pct": psutil.cpu_percent(interval=None),
            "ram_used_pct": psutil.virtual_memory().percent,
        }
    except (OSError, psutil.Error) as e:
        # Called once per hardware-monitor tick, so this stays at debug: a
        # transient read failure on a busy machine is not news, and the caller
        # keeps its last known values.
        logger.debug(f"Runtime snapshot unavailable: {e}")
        return {}
