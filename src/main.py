# src/main.py

import sys
import logging
import argparse
from typing import Dict, Any

from src.utils.logger import setup_logging, logger
from src.core.engine import TelemetryEngine
from src.backends.discovery import RuntimeCapabilityDiscovery
from src.core.exceptions import GDPRConsentError

def parse_arguments() -> argparse.Namespace:
    """
    Constructs the operational CLI argument parser for framework initialization.
    """
    parser = argparse.ArgumentParser(description="VRTelemetry: Headless Biometric Acquisition Framework")
    parser.add_argument(
        "--gdpr-consent", 
        action="store_true", 
        help="Explicitly confirm subject consent for biometric data collection. Must be provided to run."
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="Sessions", 
        help="Target directory for Parquet data matrices and SQLite metadata."
    )
    parser.add_argument(
        "--subject-id", 
        type=str, 
        default="SUB_UNKN_01", 
        help="Anonymized UUID for the active test subject."
    )
    return parser.parse_args()

def execute_pipeline() -> None:
    """
    Main orchestration bootstrapper. Extracts runtime topology, constructs capability 
    maps, and spins up the isolated tracking background layers.
    """
    setup_logging()
    args = parse_arguments()
    
    logger.info("=== VRTelemetry Pro Background Session ===")
    
    if not args.gdpr_consent:
        logger.error("Launch aborted: Biometric tracking requires explicit --gdpr-consent flag.")
        sys.exit(1)
        
    logger.info("Evaluating OpenXR hardware topology and extension capabilities...")
    hardware_capabilities: Dict[str, Any] = RuntimeCapabilityDiscovery.extract_static_hardware_metadata()
    
    logger.info(f"Detected Runtime: {hardware_capabilities.get('openxr_runtime')}")
    logger.info(f"Detected HMD: {hardware_capabilities.get('hmd_model')}")
    logger.info(f"Eye Tracking Capability: {'Available' if hardware_capabilities.get('has_eye_tracking') else 'Unavailable'}")
    
    # Engine requires robust static context for AI downstream tracking
    engine = TelemetryEngine(
        output_dir=args.output,
        gdpr_consent=args.gdpr_consent,
        hardware_metadata=hardware_capabilities
    )
    
    # Enforce static override for anonymity requirement if provided via CLI
    engine.subject_metadata["M-IV_Static_Metadata"]["subject_id"] = args.subject_id
    
    try:
        engine.start()
    except GDPRConsentError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unhandled framework panic: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    execute_pipeline()