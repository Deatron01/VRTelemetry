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
def child_env():
    """Build a subprocess environment that is controlled without being unusable.

    Two tests spawn a child process and need to dictate part of its
    environment -- a data root for one, a timezone for the other. Both built the
    whole environment from a literal::

        env={"PATH": "/usr/bin:/bin", "VRT_PATHS__DATA_ROOT": str(data_root)}

    Note what that is: not an override but a *replacement*, and a POSIX-shaped
    one. On Windows a process started without ``SystemRoot`` in its environment
    dies before it runs a line of user code -- CPython cannot seed its hash
    randomisation without it -- so both tests failed on every Windows leg of the
    matrix and passed on every Linux one. Neither test needed a scrubbed
    ``PATH`` in the first place: both launch an absolute executable.

    Inheriting and then overriding gives the same control -- the caller still
    decides every variable it cares about -- without also deciding, by
    omission, that the operating system needs nothing.

    Args:
        drop_prefix: Environment variables starting with this are removed
            before the overrides are applied, so an ambient ``VRT_...`` setting
            on a developer's machine cannot reach the child.
        **overrides: Applied last, and therefore always win.
    """

    def build(*, drop_prefix: str | None = None, **overrides: str) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if drop_prefix is None or not key.startswith(drop_prefix)
        }
        env.update(overrides)
        return env

    return build


@pytest.fixture
def mock_telemetry_frame():
    """
    Provides a standardized, empty telemetry frame pre-allocated for
    1D Tensor injection testing.
    """
    from src.core.datatypes import TelemetryFrame

    return TelemetryFrame.create_empty(frame_idx=0)


@pytest.fixture
def consent_payload():
    """Build the body the consent screen sends, for the configured wording (GDPR-09).

    Every participant box ticked and both researcher confirmations given, with
    the hash of every text -- i.e. a consent the server accepts. Tests that
    need a refusal change one field of the result.

    Args (of the returned builder):
        consent_settings: The ``[consent]`` section the application under test
            was built with. Defaults to the defaults, which is what every
            test container uses unless it says otherwise.
    """
    from src.config import ConsentSettings
    from src.patients.consent_texts import RESEARCHER, build_catalogue

    def build(consent_settings: ConsentSettings | None = None) -> dict:
        catalogue = build_catalogue(consent_settings or ConsentSettings())
        return {
            "text_version": catalogue.text_version,
            "language": "en",
            "choices": {i.id: True for i in catalogue.items if i.group != RESEARCHER},
            "researcher_confirmations": {
                i.id: True for i in catalogue.items if i.group == RESEARCHER
            },
            "displayed_sha256": {i.id: i.sha256 for i in catalogue.items},
        }

    return build
