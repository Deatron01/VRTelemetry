# src/interfaces/cli/record.py
"""Headless acquisition CLI (VRT-10).

Moved out of src/main.py, where the argparse entry point shared a module with
the entire HTTP API. The two have nothing in common beyond both starting a
TelemetryEngine, and keeping them together meant every API import paid for the
CLI and vice versa.

Installed as the ``vrtelemetry-record`` console script.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from src.backends.discovery import RuntimeCapabilityDiscovery
from src.core.engine import TelemetryEngine
from src.core.exceptions import GDPRConsentError
from src.eye_tracking.factory import EyeTrackingFactory
from src.utils.logger import logger, setup_logging
from src.utils.metadata import sanitize_metadata


def parse_arguments() -> argparse.Namespace:
    """
    Constructs the operational CLI argument parser for framework initialization.
    """
    parser = argparse.ArgumentParser(
        description="VRTelemetry: Headless Biometric Acquisition Framework"
    )
    parser.add_argument(
        "--gdpr-consent",
        action="store_true",
        help="Explicitly confirm subject consent for biometric data collection. Must be provided to run.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Target directory for Parquet data matrices and SQLite metadata.",
    )
    parser.add_argument(
        "--subject-id",
        type=str,
        default="SUB_UNKN_01",
        help="Anonymized UUID for the active test subject.",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["auto", "openxr", "oculus", "steamvr", "quest_udp"],
        default="auto",
        help="Enforce a specific runtime hardware backend wrapper or standalone network telemetry worker.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5005,
        help="Incoming network port target when operating under 'quest_udp' stream backend mode.",
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

    logger.info(f"Selected execution pipeline mode: Enforced Backend -> [{args.backend.upper()}]")
    logger.debug(f"Eye-tracking driver registry: {EyeTrackingFactory._registry}")
    # Extract native runtime metadata if standard PCVR hardware mode is active
    if args.backend != "quest_udp":
        logger.info("Evaluating OpenXR hardware topology and extension capabilities...")
        raw_hardware_capabilities: dict[str, Any] = (
            RuntimeCapabilityDiscovery.extract_static_hardware_metadata()
        )
        hardware_capabilities = sanitize_metadata(raw_hardware_capabilities)
    else:
        # Generate virtual network context payload mapping for Quest standalone stream
        hardware_capabilities = {
            "openxr_runtime": "Quest_OVRPlugin_Standalone",
            "hmd_model": "Meta Quest Pro",
            "has_eye_tracking": True,
            "transport_protocol": "UDP_Network_Socket",
            "binding_port": args.port,
        }

    logger.info(f"Detected Runtime: {hardware_capabilities.get('openxr_runtime')}")
    logger.info(f"Detected HMD: {hardware_capabilities.get('hmd_model')}")
    logger.info(
        f"Eye Tracking Capability: {'Available' if hardware_capabilities.get('has_eye_tracking') else 'Unavailable'}"
    )

    # Engine requires robust static context for AI downstream tracking
    engine = TelemetryEngine(
        output_dir=args.output,
        gdpr_consent=args.gdpr_consent,
        hardware_metadata=hardware_capabilities,
    )

    # Inject runtime execution configurations into context maps before startup sequence
    engine.subject_metadata["M-IV_Static_Metadata"]["subject_id"] = args.subject_id

    # Inform backend engine context regarding specific protocol drivers
    engine.configured_backend = args.backend
    engine.network_port = args.port

    try:
        engine.start()
    except GDPRConsentError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unhandled framework panic: {e}", exc_info=True)
        sys.exit(1)
