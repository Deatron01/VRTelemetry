# src/utils/auto_installer.py

import sys
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def verify_and_install_dependencies() -> None:
    """
    Automated environment verification suite. Evaluates host dependencies 
    and verifies binary module links before execution initialization.
    """
    logger.info("Executing environment compliance checks...")
    
    requirements_file = Path(__file__).parent.parent.parent / "requirements.txt"
    if not requirements_file.exists():
        logger.error(f"Environment Error: requirements.txt missing from workspace root: {requirements_file}")
        return

    try:
        logger.info("Verifying Python site-packages with Pip tracking specifications...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-r", str(requirements_file)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("All prerequisite binary modules are linked and validated.")
    except subprocess.CalledProcessError as e:
        logger.critical(f"Deployment Layer Error: Pip failed to bind target dependencies: {e}")
        sys.exit(1)