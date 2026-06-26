import logging
import logging.handlers
import queue
import atexit
from pathlib import Path

def setup_async_logger(log_dir: str = "Logs", level: int = logging.INFO) -> logging.Logger:
    """
    Sets up a non-blocking, thread-safe asynchronous logger.
    Ensures that writing logs to the disk does not interfere with the 120Hz telemetry loop.
    """
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    logger = logging.getLogger("VRTelemetry")
    logger.setLevel(level)
    
    # Prevent adding handlers multiple times if instantiated repeatedly
    if logger.handlers:
        return logger

    # 1. Standard formatters
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(threadName)-12s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 2. File Handler (Rotating to prevent massive log files)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_path / "vr_telemetry_engine.log",
        maxBytes=5 * 1024 * 1024, # 5 MB
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # 3. Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 4. Asynchronous Queue setup
    log_queue = queue.Queue(maxsize=1000)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    
    # 5. The QueueListener runs on its own background thread automatically
    listener = logging.handlers.QueueListener(
        log_queue, file_handler, console_handler, respect_handler_level=True
    )

    logger.addHandler(queue_handler)
    listener.start()
    
    # Ensure the listener flushes the queue when the application shuts down
    atexit.register(listener.stop)

    return logger

# Global instance to be imported by other modules
logger = setup_async_logger()