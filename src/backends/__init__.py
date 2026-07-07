from src.backends.backend_openxr import OpenXRBackend
from src.backends.backend_steamvr import SteamVRBackend
from src.backends.backend_ocolus import OculusBackend
from src.core.interfaces import IVRBackend
from src.utils.logger import logger

def discover_active_backend() -> IVRBackend:
    """
    Interrogates connected runtime layers to determine the best backend configuration.
    Falls back gracefully if primary OpenXR runtimes are sleep-locked.
    """
    logger.info("Initiating runtime automated discovery protocols...")
    
    # 1. Try Production OpenXR Backend
    oxr = OpenXRBackend()
    if oxr.initialize():
        logger.info("Primary OpenXR Engine context established active pipeline.")
        return oxr

    # 2. Try Native Oculus SDK Fallback Interface
    oculus = OculusBackend()
    if oculus.initialize():
        logger.info("Native Oculus LibOVR fallback context initialized successfully.")
        return oculus

    # 3. Try Legacy SteamVR/OpenVR Platform Services
    ovr = SteamVRBackend()
    if ovr.initialize():
        logger.info("Legacy SteamVR fallback context initialized successfully.")
        return ovr

    raise RuntimeWarning("CRITICAL: Environment possesses no active VR system runtimes.")