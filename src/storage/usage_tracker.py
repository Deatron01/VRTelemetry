# src/storage/usage_tracker.py — new file

import logging
import sqlite3
import uuid
from pathlib import Path

from src.config import get_settings
from src.version import APP_VERSION

logger = logging.getLogger(__name__)


class UsageTracker:
    """
    App-level interaction telemetry — page views, session-start/stop actions,
    export usage. Deliberately separate from biometric session_metadata:
    different consent scope (application usage vs. subject biometrics),
    different lifecycle (spans across many recording sessions, not one).
    """

    def __init__(self, db_path: str | Path | None = None):
        # Resolved at call time, not as a default argument: a default is
        # evaluated once at import and would freeze the path before any
        # configuration could be read. See src/config/settings.py (VRT-6).
        self.db_path = Path(db_path) if db_path else get_settings().paths.usage_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,     -- page_view | recording_start | recording_stop | export | sync
                    detail TEXT,
                    researcher_email TEXT,
                    app_version TEXT,
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def log_event(
        self,
        event_type: str,
        detail: str = "",
        researcher_email: str = "",
        app_version: str = APP_VERSION,
    ) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO usage_events (event_id, event_type, detail, researcher_email, app_version)
                       VALUES (?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), event_type, detail, researcher_email, app_version),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.debug(f"Usage event logging failed (non-critical): {e}")
