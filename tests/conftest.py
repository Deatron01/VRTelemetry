# tests/conftest.py

import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Session-wide test fixture. Ensures a clean state for storage directories
    before and after the entire test suite runs, preventing Parquet/SQLite
    artifacts from polluting the developer workspace.
    """
    test_session_dir = Path("Tests/TempSessions")
    test_log_dir = Path("Tests/TempLogs")

    # Pre-test cleanup (in case of previous aborted runs)
    if test_session_dir.exists():
        shutil.rmtree(test_session_dir)
    if test_log_dir.exists():
        shutil.rmtree(test_log_dir)

    test_session_dir.mkdir(parents=True)
    test_log_dir.mkdir(parents=True)

    # Inject environment variables to redirect standard paths during tests
    os.environ["VRTELEMETRY_STORAGE_DIR"] = str(test_session_dir)
    os.environ["VRTELEMETRY_LOG_DIR"] = str(test_log_dir)

    yield  # Yield control to PyTest execution phase

    # Post-test teardown
    if test_session_dir.exists():
        shutil.rmtree(test_session_dir, ignore_errors=True)
    if test_log_dir.exists():
        shutil.rmtree(test_log_dir, ignore_errors=True)


@pytest.fixture
def mock_telemetry_frame():
    """
    Provides a standardized, empty telemetry frame pre-allocated for
    1D Tensor injection testing.
    """
    from src.core.datatypes import TelemetryFrame

    return TelemetryFrame.create_empty(frame_idx=0)
