# src/utils/system_profiler.py

import platform
import socket
import getpass
import logging
import uuid as uuid_lib
from typing import Dict, Any

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def collect_system_profile() -> Dict[str, Any]:
    """
    Captures a snapshot of the host machine and environment at session start.
    This is part of the same consented data-collection scope as biometric
    telemetry (see GDPRConsentError) — it travels inside session metadata,
    not as a separate uncontrolled collection channel.
    """
    profile: Dict[str, Any] = {
        "os_name": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "cpu_name": platform.processor() or "Unknown",
    }

    try:
        profile["os_user"] = getpass.getuser()
    except Exception:
        profile["os_user"] = "Unknown"

    if PSUTIL_AVAILABLE:
        try:
            vm = psutil.virtual_memory()
            profile["total_ram_gb"] = round(vm.total / (1024 ** 3), 2)
            profile["cpu_cores_logical"] = psutil.cpu_count(logical=True)
            profile["cpu_cores_physical"] = psutil.cpu_count(logical=False)
            profile["cpu_freq_mhz"] = getattr(psutil.cpu_freq(), "max", None)

            disk = psutil.disk_usage('/')
            profile["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
            profile["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)

            battery = psutil.sensors_battery()
            if battery:
                profile["host_battery_pct"] = battery.percent
                profile["host_on_ac_power"] = battery.power_plugged
        except Exception as e:
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
        import subprocess
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip() and "Name" not in l]
            return ", ".join(lines) if lines else "Unknown"
        elif platform.system() == "Linux":
            result = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            gpu_lines = [l for l in result.stdout.splitlines() if "VGA" in l or "3D controller" in l]
            return "; ".join(gpu_lines) if gpu_lines else "Unknown"
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip()[:500] if result.stdout else "Unknown"
    except Exception as e:
        logger.debug(f"GPU info collection failed: {e}")
    return "Unknown"


def collect_runtime_snapshot() -> Dict[str, Any]:
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
    except Exception:
        return {}