import sys
import time
import pytest
from pathlib import Path

class VRTestRunner:
    """
    Dedicated automated test runner for VRTelemetry_Pro.
    Handles discovery, execution, HTML/JSON reporting, and CI/CD exit codes.
    """
    def __init__(self):
        self.root_dir = Path(__file__).parent.parent
        self.reports_dir = self.root_dir / "reports"
        self.reports_dir.mkdir(exist_ok=True)
        
    def run_all(self) -> int:
        """Executes the entire testing framework (Unit, Integration, Stress)."""
        print("="*60)
        print("🧪 VRTelemetry Pro - Automated QA Test Runner")
        print("="*60)
        
        start_time = time.time()
        
        # Configure pytest arguments for deep reporting
        args = [
            str(self.root_dir / "tests"),
            "-v",
            f"--html={self.reports_dir / 'test_report.html'}",
            "--self-contained-html",
            "--cov=src",
            f"--cov-report=html:{self.reports_dir / 'coverage_html'}",
            f"--cov-report=json:{self.reports_dir / 'coverage.json'}",
            "--cov-report=term"
        ]
        
        print("[*] Initiating test discovery and execution...")
        exit_code = pytest.main(args)
        
        duration = time.time() - start_time
        
        print("\n" + "="*60)
        if exit_code == 0:
            print(f"✅ ALL TESTS PASSED ({duration:.2f} seconds)")
        else:
            print(f"❌ TEST SUITE FAILED (Exit Code: {exit_code})")
            
        print(f"📊 Detailed HTML Report: {self.reports_dir / 'test_report.html'}")
        print(f"📈 Coverage Report: {self.reports_dir / 'coverage_html' / 'index.html'}")
        print("="*60)
        
        return exit_code

if __name__ == "__main__":
    runner = VRTestRunner()
    sys.exit(runner.run_all())