import subprocess
import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools"

# Define the sequence of scripts to execute
PIPELINE_SCRIPTS = [
    "generate_docs.py",
    "merge_and_clean_docs.py",
    "clean_svgs.py",
    "generate_graphs.py",  # Assumes your Mermaid conversion script is named this (adjust if named generate_graphs.py)
    "append_structure.py",
]


def run_script(script_name: str):
    script_path = TOOLS_DIR / script_name

    # Fallback check if the script is named generate_graphs.py instead of mermaid_converter.py
    if not script_path.exists() and script_name == "mermaid_converter.py":
        alt_path = TOOLS_DIR / "generate_graphs.py"
        if alt_path.exists():
            script_path = alt_path
            script_name = "generate_graphs.py"

    if not script_path.exists():
        print(f"[!] Warning: Script not found: {script_path}. Skipping...")
        return True

    print("\n==========================================")
    print(f"[>] Running step: {script_name}")
    print("==========================================")

    try:
        # Run using the same python interpreter currently active
        result = subprocess.run([sys.executable, str(script_path)], check=True, text=True)
        print(f"[✓] Successfully completed: {script_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[✗] Error executing {script_name}: exited with code {e.returncode}")
        return False
    except OSError as e:
        # The interpreter or the script path could not be executed at all,
        # which CalledProcessError above does not cover. Narrowed so that a bug
        # in this launcher is not reported to the operator as a failure of the
        # step it was trying to run.
        print(f"[✗] Could not start {script_name}: {e}")
        return False


def main():
    print("[+] Starting Documentation Master Pipeline...")

    for script in PIPELINE_SCRIPTS:
        success = run_script(script)
        if not success:
            print(f"\n[!] Pipeline halted due to an error in {script}.")
            sys.exit(1)

    print("\n[✓] Entire documentation pipeline completed successfully!")


if __name__ == "__main__":
    main()
