import sys
from pathlib import Path

# Initialize environment checks before loading dependencies
sys.path.append(str(Path(__file__).parent.parent))
from src.utils.auto_installer import ensure_dependencies

if __name__ == "__main__":
    ensure_dependencies()
    from src.core.engine import TelemetryEngine
    
    # Explicitly pass gdpr_consent=True to allow biometric 
    # and hardware profiling data to write to disk safely.
    engine = TelemetryEngine(target_hz=90, output_dir="Sessions", gdpr_consent=True)
    engine.start()