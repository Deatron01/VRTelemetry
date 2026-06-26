import sys
import subprocess
import pkg_resources
from pathlib import Path

def ensure_dependencies() -> None:
    """
    Compares the current Python environment against requirements.txt.
    Automatically provisions missing wheels silently before core execution.
    """
    req_file = Path(__file__).parent.parent.parent / "requirements.txt"
    if not req_file.exists():
        return

    with open(req_file, "r", encoding="utf-8") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    missing = []
    for req in requirements:
        try:
            pkg_name = req.split("==")[0].split(">=")[0]
            pkg_resources.get_distribution(pkg_name)
        except pkg_resources.DistributionNotFound:
            missing.append(req)

    if missing:
        print(f"[*] Missing dependencies detected: {', '.join(missing)}")
        print("[*] Automatically installing prerequisites via pip...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", *missing],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("[+] Environment configuration synchronized successfully.")
        except subprocess.CalledProcessError as e:
            print(f"[!] Critical error initializing Python workspace: {e}")
            sys.exit(1)