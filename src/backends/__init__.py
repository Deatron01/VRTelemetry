from src.backends.backend_openxr import OpenXRBackend
from src.backends.backend_steamvr import SteamVRBackend
from src.core.interfaces import IVRBackend

def discover_active_backend() -> IVRBackend:
    """
    Interrogates connected runtime layers to determine the best backend configuration.
    Falls back gracefully if primary OpenXR runtimes are sleep-locked.
    """
    print("[*] Initiating runtime automated discovery protocols...")
    oxr = OpenXRBackend()
    if oxr.initialize():
        print("[+] Primary OpenXR Engine context established active pipeline.")
        return oxr

    print("[!] OpenXR context missing or unavailable. Falling back to OpenVR platform services...")
    ovr = SteamVRBackend()
    if ovr.initialize():
        print("[+] Legacy SteamVR fallback context initialized successfully.")
        return ovr

    raise RuntimeWarning("CRITICAL: Environment possesses no active VR system runtimes.")