# src/utils/logger.py

import logging
import sys
from pathlib import Path
from typing import Optional

def setup_logging(log_dir: str = "Logs", log_level: int = logging.INFO) -> None:
    """
    Configures a globally accessible, thread-safe logging infrastructure targeting
    both stdout and physical log files. Uses explicit UTF-8 encoding.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    log_file = log_path / "vr_telemetry_engine.log"
    
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(threadName)-15s] [%(name)-20s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Flush existing handlers if re-initialized
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.setLevel(log_level)
    
    # Console Output (Standard out to avoid stderr stream pollution unless necessary)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File Output
    file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Suppress verbose debug output from third party libraries unless critical
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("xr").setLevel(logging.WARNING)



def attach_session_log_capture(session_id: str, log_dir: str = "Sessions/logs") -> logging.Handler:
    """
    Adds a second file handler scoped to one recording session, capturing
    everything logged at INFO+ during that session — including driver
    resolution reasoning, OpenXR extension enumeration, and any warnings/errors
    the hardware backends emit. Runs alongside the global engine log, not
    instead of it.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_path = log_path / f"session_{session_id}.log"

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(threadName)-15s] [%(name)-20s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler = logging.FileHandler(file_path, encoding="utf-8", mode="w")
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)

    logging.getLogger().addHandler(handler)
    handler._session_log_path = file_path  # stashed for retrieval on detach
    return handler


def detach_session_log_capture(handler: logging.Handler) -> Optional[Path]:
    """Seals the session log — call this once the session is fully finished."""
    logging.getLogger().removeHandler(handler)
    path = getattr(handler, "_session_log_path", None)
    handler.close()
    return path

# Expose singleton logger target for standard framework imports
logger = logging.getLogger("VRTelemetry")