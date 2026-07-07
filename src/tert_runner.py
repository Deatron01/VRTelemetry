# src/tert_runner.py

import sys
import logging
from pathlib import Path

from src.utils.auto_installer import verify_and_install_dependencies
from src.utils.logger import setup_logging, logger
from src.main import execute_pipeline

def boot_framework_context() -> None:
    """
    Administrative initialization entry point. Validates package alignment,
    configures active thread pools, and pipes signals to the main process router.
    """
    setup_logging()
    
    # Auto-verify environment structures prior to loading memory-sensitive C extensions
    verify_and_install_dependencies()
    
    logger.info("Bootstrapping complete. Transferring thread handles to system main pipeline.")
    execute_pipeline()

if __name__ == "__main__":
    boot_framework_context()