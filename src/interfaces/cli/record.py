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

from src.application.consent import ConsentService
from src.backends.discovery import RuntimeCapabilityDiscovery
from src.backends.registry import known_backends
from src.config import get_settings
from src.core.engine import TelemetryEngine
from src.core.exceptions import GDPRConsentError
from src.eye_tracking.factory import EyeTrackingFactory
from src.infrastructure.persistence.consent_repository import ConsentRepository
from src.patients.consent_texts import build_catalogue
from src.utils.logger import logger, setup_logging
from src.utils.metadata import sanitize_metadata


def build_parser() -> argparse.ArgumentParser:
    """The operational CLI argument parser.

    Separate from :func:`parse_arguments` so a test can inspect the options
    without driving ``sys.argv`` or catching ``SystemExit`` -- specifically, so
    the test that the ``--backend`` choices match the registry can read them.
    """
    parser = argparse.ArgumentParser(
        description="VRTelemetry: Headless Biometric Acquisition Framework"
    )
    parser.add_argument(
        "--consent-id",
        type=str,
        default=None,
        help=(
            "The participant consent this recording is made under, from the consent register "
            "(shown in the desktop app and returned by POST /api/patients). Required."
        ),
    )
    # The old flag. Kept only so that using it produces an explanation rather
    # than argparse's bare "unrecognized arguments" (GDPR-09).
    parser.add_argument("--gdpr-consent", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Target directory for Parquet data matrices and SQLite metadata.",
    )
    parser.add_argument(
        "--subject-id",
        type=str,
        default=None,
        help="Pseudonymous subject label. Defaults to the consent's patient id.",
    )
    parser.add_argument(
        "--backend",
        type=str,
        # Built from the registry rather than hand-listed, so a backend added
        # there is selectable here without a second edit that someone will
        # forget. "quest_udp" is appended because it is a different loop shape
        # rather than a backend -- see src/backends/registry.py.
        choices=["auto", *known_backends(), "quest_udp"],
        default="auto",
        help="Enforce a specific runtime hardware backend wrapper or standalone network telemetry worker.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5005,
        help="Incoming network port target when operating under 'quest_udp' stream backend mode.",
    )
    return parser


def _consent_service() -> ConsentService:
    """The consent register for this installation's patients database."""
    settings = get_settings()
    return ConsentService(
        ConsentRepository(settings.paths.patients_db),
        catalogue_provider=lambda: build_catalogue(settings.consent),
    )


def _patient_for_consent(consent_id: str) -> str:
    """The participant a consent id belongs to; unknown ids are refused downstream."""
    record = _consent_service().repository.get(consent_id)
    return record["patient_id"] if record else ""


def parse_arguments() -> argparse.Namespace:
    """Parse ``sys.argv`` with :func:`build_parser`."""
    return build_parser().parse_args()


def execute_pipeline() -> None:
    """
    Main orchestration bootstrapper. Extracts runtime topology, constructs capability
    maps, and spins up the isolated tracking background layers.
    """
    setup_logging()
    args = parse_arguments()

    logger.info("=== VRTelemetry Pro Background Session ===")

    if args.backend == "quest_udp" and not get_settings().acquisition.enable_quest_udp:
        logger.error(
            "Launch aborted: the quest_udp backend is disabled (acquisition.enable_quest_udp). "
            "Its receiver accepts unencrypted, unauthenticated telemetry from the network (GDPR-12)."
        )
        sys.exit(1)

    if not args.consent_id:
        if args.gdpr_consent:
            logger.error(
                "Launch aborted: --gdpr-consent is no longer accepted. A flag records only that "
                "someone typed it; it is not evidence of the participant's consent (GDPR-09). "
                "Record the participant's consent in the desktop app and pass --consent-id."
            )
        else:
            logger.error("Launch aborted: --consent-id is required.")
        sys.exit(1)

    try:
        consent = _consent_service().require_for_recording(
            _patient_for_consent(args.consent_id), args.consent_id
        )
    except GDPRConsentError as e:
        logger.error(f"Launch aborted: {e}")
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
        gdpr_consent=True,  # established above, from the consent register
        hardware_metadata=hardware_capabilities,
        backend=args.backend,
        network_port=args.port,
    )

    # Inject runtime execution configurations into context maps before startup sequence
    static = engine.subject_metadata["M-IV_Static_Metadata"]
    static["subject_id"] = args.subject_id or consent["patient_id"]
    static["patient_id"] = consent["patient_id"]
    static["consent_id"] = consent["consent_id"]

    try:
        engine.start()
    except GDPRConsentError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 - process top level: the alternative is a bare traceback
        # The outermost frame of the `vrtelemetry-record` console script. There
        # is nothing above it but the interpreter, so this catch converts a
        # crash into a logged failure and an exit status -- with the traceback
        # kept (`exc_info=True`), which is the part that distinguishes this from
        # swallowing. The engine has already recorded `failure_reason` for the
        # cases it anticipated; this is for the ones it did not.
        logger.critical(f"Unhandled framework panic: {e}", exc_info=True)
        sys.exit(1)
