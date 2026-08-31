# src/utils/logger.py

import logging
import sys
from pathlib import Path

from src.config import get_settings
from src.utils.log_redaction import PersonalDataFilter


def setup_logging(log_dir: str | Path | None = None, log_level: int = logging.INFO) -> None:
    """
    Configures a globally accessible, thread-safe logging infrastructure targeting
    both stdout and physical log files. Uses explicit UTF-8 encoding.
    """
    log_path = Path(log_dir) if log_dir else get_settings().paths.logs_dir
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / "vr_telemetry_engine.log"

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(threadName)-15s] [%(name)-20s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Flush existing handlers if re-initialized
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.setLevel(log_level)

    # Defence in depth for VRT-3. The primary fix is at the call sites (log
    # field names, never field values); this filter catches the call site that
    # has not been written yet.
    #
    # Attached to each *handler*, not to the root logger. A filter on a Logger
    # runs only for records logged through that logger directly: Logger.handle()
    # applies its own filters and then calls callHandlers(), which walks the
    # ancestors' handlers but never their filters. Since every call site here
    # uses the "VRTelemetry" child logger, a root-logger filter would silently
    # never run — which is the worst possible outcome for a redaction control.
    redaction_filter = PersonalDataFilter()

    # Console Output (Standard out to avoid stderr stream pollution unless necessary)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redaction_filter)
    root_logger.addHandler(console_handler)

    # File Output
    file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redaction_filter)
    root_logger.addHandler(file_handler)

    # Suppress verbose debug output from third party libraries unless critical
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("xr").setLevel(logging.WARNING)


def attach_session_log_capture(
    session_id: str, log_dir: str | Path | None = None
) -> logging.Handler:
    """
    Adds a second file handler scoped to one recording session, capturing
    everything logged at INFO+ during that session — including driver
    resolution reasoning, OpenXR extension enumeration, and any warnings/errors
    the hardware backends emit. Runs alongside the global engine log, not
    instead of it.
    """
    log_path = Path(log_dir) if log_dir else get_settings().paths.logs_dir
    log_path.mkdir(parents=True, exist_ok=True)
    file_path = log_path / f"session_{session_id}.log"

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(threadName)-15s] [%(name)-20s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.FileHandler(file_path, encoding="utf-8", mode="w")
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    # Session logs are uploaded to the central server by SessionUploader.upload_log,
    # so an unredacted record here would leave the machine. Same filter as the
    # global sinks — see setup_logging for why it goes on the handler.
    handler.addFilter(PersonalDataFilter())

    logging.getLogger().addHandler(handler)
    handler._session_log_path = file_path  # stashed for retrieval on detach
    return handler


def detach_session_log_capture(handler: logging.Handler) -> Path | None:
    """Seals the session log — call this once the session is fully finished."""
    logging.getLogger().removeHandler(handler)
    path = getattr(handler, "_session_log_path", None)
    handler.close()
    return path


# Expose singleton logger target for standard framework imports
logger = logging.getLogger("VRTelemetry")
