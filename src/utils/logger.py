# src/utils/logger.py

import logging
import sys
from pathlib import Path

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

# Expose singleton logger target for standard framework imports
logger = logging.getLogger("VRTelemetry")