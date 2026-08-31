"""SQLite persistence (VRT-11).

Everything that opens a database connection lives here. The rule the layer
exists to enforce: no module outside this package imports ``sqlite3``.
"""

from src.infrastructure.persistence.connection import connect, transaction
from src.infrastructure.persistence.migrations import current_version, migrate
from src.infrastructure.persistence.session_repository import SessionRepository

__all__ = ["SessionRepository", "connect", "current_version", "migrate", "transaction"]
