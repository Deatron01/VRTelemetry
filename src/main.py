import sys
import argparse

# 1. Pre-flight check: Auto-install dependencies before anything else
from utils.auto_installer import ensure_dependencies
ensure_dependencies()

# 2. Safe imports (Executed only after we know dependencies exist)
from core.engine import TelemetryEngine

def main():
    parser = argparse.ArgumentParser(description="Professional High-Frequency VR Telemetry")
    parser.add_argument("--hz", type=int, default=90, choices=[72, 80, 90, 120, 144], 
                        help="Target polling frequency (Hz). Default is 90.")
    parser.add_argument("--output", type=str, default="Sessions", 
                        help="Output directory for parquet files.")
    
    args = parser.parse_args()

    engine = TelemetryEngine(target_hz=args.hz, output_dir=args.output)
    engine.start()

if __name__ == "__main__":
    main()