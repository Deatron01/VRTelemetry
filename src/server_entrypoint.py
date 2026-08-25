# src/server_entrypoint.py

import sys
import logging
import uvicorn

from src.utils.logger import setup_logging, logger
from src.main import app

def boot_server_context() -> None:
    """
    Desktop-app entry point. Boots the FastAPI server that the Electron-hosted 
    frontend communicates with over HTTP, as opposed to tert_runner.py's direct 
    CLI polling pipeline.
    """
    setup_logging()
    logger.info("Bootstrapping VRTelemetry backend server for desktop shell...")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    boot_server_context()