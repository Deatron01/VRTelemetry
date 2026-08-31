# src/tert_runner.py

from src.main import execute_pipeline
from src.utils.logger import logger, setup_logging


def boot_framework_context() -> None:
    """CLI entry point for a direct, headless acquisition run.

    Installed as the ``vrtelemetry-record`` console script. This is the polling
    pipeline, not the HTTP server -- ``src/server_entrypoint.py`` is what the
    Electron shell spawns.

    Previously this called ``verify_and_install_dependencies()``, which shelled
    out to ``pip install -r requirements.txt`` on every launch with output sent
    to DEVNULL. That has been removed. A program that mutates its own
    environment at startup means two runs a week apart are not the same
    software, which is indefensible for a tool recording research data: a
    silently upgraded pyarrow can change how a Parquet file is written mid-study
    with nothing in the record to show it. It also could not work at all inside
    the frozen PyInstaller bundle the desktop app ships, and it swallowed the
    output that would have explained any failure.

    Environment construction now belongs to the installer:

        pip install -e ".[workstation]"
    """
    setup_logging()
    logger.info("Bootstrapping VRTelemetry acquisition pipeline...")
    execute_pipeline()


if __name__ == "__main__":
    boot_framework_context()
