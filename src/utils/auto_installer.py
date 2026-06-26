import sys
import subprocess
import pkg_resources
from pathlib import Path

def ensure_dependencies() -> None:
    """
    Checks installed packages against requirements.txt.
    Installs missing dependencies automatically using pip.
    """
    req_file = Path(__file__).parent.parent.parent / "requirements.txt"
    
    if not req_file.exists():
        print(f"[!] Warning: {req_file.name} not found. Skipping auto-install.")
        return

    with open(req_file, "r") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    missing = []
    for req in requirements:
        try:
            # Strip version specifiers to check base package name
            pkg_name = req.split("==")[0].split(">=")[0]
            pkg_resources.get_distribution(pkg_name)
        except pkg_resources.DistributionNotFound:
            missing.append(req)

    if missing:
        print(f"[*] Missing dependencies detected: {', '.join(missing)}")
        print("[*] Installing missing packages. Please wait...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", *missing],
                stdout=subprocess.DEVNULL
            )
            print("[+] Dependencies successfully installed.")
        except subprocess.CalledProcessError as e:
            print(f"[!] Error installing dependencies: {e}")
            sys.exit(1)