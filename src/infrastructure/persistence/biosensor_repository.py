# src/infrastructure/persistence/biosensor_repository.py
"""Per-session, per-device provenance record for biosensor streams (VRT-34).

Its own table, not columns on ``session_metadata`` -- same reasoning as
``av_recording_repository.py``: this data is optional, comes from a
third-party plugin process, and needs to be queryable and erasable on its
own (a future ``WithdrawalScope.BIOSENSOR_ONLY``, host-changes doc §6)
without touching the 78-column INSERT that VRT-22 already showed is the
wrong place to bolt anything onto.

This table is the *provenance* record -- which device sent what, how much,
when. The actual sample values live in the per-session sidecar Parquet
(``src.storage.biosensor_sidecar``), never in SQLite: a raw-ECG channel at
130 Hz would make this table the write bottleneck of the whole ingest path
within a session or two.

Follows ``av_recording_repository.py``'s pattern: self-contained
``CREATE TABLE IF NOT EXISTS`` in the constructor, not the versioned
``migrations`` module -- that module's baselining logic exists for
``session_metadata``'s specific history and would be the wrong tool for a
table with no rows to baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.infrastructure.persistence.connection import transaction

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS biosensor_streams (
        session_id            TEXT NOT NULL,
        device_id              TEXT NOT NULL,
        producer_id             TEXT,
        channels_json           TEXT NOT NULL DEFAULT '[]',
        samples_accepted        INTEGER NOT NULL DEFAULT 0,
        samples_dropped         INTEGER NOT NULL DEFAULT 0,
        first_sample_at_utc     TEXT,
        last_sample_at_utc      TEXT,
        PRIMARY KEY (session_id, device_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_biosensor_streams_session ON biosensor_streams(session_id)",
)


class BiosensorStreamRepository:
    """Reads and writes ``biosensor_streams``. One row per (session, device)."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        with transaction(self.db_path) as conn:
            for statement in _SCHEMA:
                conn.execute(statement)

    def record_batch(
        self,
        *,
        session_id: str,
        device_id: str,
        producer_id: str | None,
        channels: set[str],
        accepted: int,
        dropped: int,
        received_at_utc: str,
    ) -> None:
        """Upsert one ingest request's worth of activity for (session_id, device_id).

        Called once per ``POST /api/biosensors/sample`` call (not once per
        sample) -- see the ingest route -- so this is at most a few writes
        per second even against a 130 Hz channel batched sensibly.
        """
        with transaction(self.db_path) as conn:
            existing = conn.execute(
                "SELECT channels_json FROM biosensor_streams "
                "WHERE session_id = ? AND device_id = ?",
                (session_id, device_id),
            ).fetchone()

            if existing is None:
                conn.execute(
                    """INSERT INTO biosensor_streams (
                           session_id, device_id, producer_id, channels_json,
                           samples_accepted, samples_dropped,
                           first_sample_at_utc, last_sample_at_utc
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        device_id,
                        producer_id,
                        json.dumps(sorted(channels)),
                        accepted,
                        dropped,
                        received_at_utc,
                        received_at_utc,
                    ),
                )
                return

            merged_channels = sorted(set(json.loads(existing["channels_json"])) | channels)
            conn.execute(
                """UPDATE biosensor_streams SET
                       producer_id = ?, channels_json = ?,
                       samples_accepted = samples_accepted + ?,
                       samples_dropped = samples_dropped + ?,
                       last_sample_at_utc = ?
                   WHERE session_id = ? AND device_id = ?""",
                (
                    producer_id,
                    json.dumps(merged_channels),
                    accepted,
                    dropped,
                    received_at_utc,
                    session_id,
                    device_id,
                ),
            )

    def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM biosensor_streams WHERE session_id = ?", (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_for_sessions(self, session_ids: list[str]) -> int:
        """Delete rows for the given sessions. For right-to-erasure paths (VRT-37).

        Returns:
            How many rows were deleted.
        """
        if not session_ids:
            return 0
        placeholders = ", ".join("?" * len(session_ids))
        with transaction(self.db_path) as conn:
            cursor = conn.execute(
                f"DELETE FROM biosensor_streams WHERE session_id IN ({placeholders})",  # noqa: S608 - placeholders only
                session_ids,
            )
            return cursor.rowcount
