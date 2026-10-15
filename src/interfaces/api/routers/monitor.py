# src/interfaces/api/routers/monitor.py
import contextlib
import subprocess

from fastapi import APIRouter

from src.utils.system_profiler import collect_runtime_snapshot

router = APIRouter(tags=["monitor"])


@router.get("/api/monitor/metrics")
def get_metrics():
    """Live PC performance metrics for the monitoring window."""
    metrics = collect_runtime_snapshot()

    # GPU utilization (similar to HardwareMonitor)
    gpu_pct = -1.0
    with contextlib.suppress(Exception):
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        if result.stdout.strip():
            gpu_pct = float(result.stdout.strip().splitlines()[0])

    metrics["gpu_load_pct"] = gpu_pct
    return metrics
