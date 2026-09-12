# src/infrastructure/persistence/av_recording_repository.py
"""Metadata for A/V recordings: one row per session that had one attempted.

Deliberately its own table in ``metadata_db``, not columns bolted onto
``session_metadata``. Two reasons:

* ``session_metadata``'s 78-column INSERT (see
  ``src.storage.database_manager.SESSION_METADATA_COLUMNS``) is exactly the
  shape of thing VRT-22 happened to -- a column added to the CREATE TABLE
  without its matching migration silently discarded every session's metadata
  for days. A/V recording is new, optional (``ConsentSettings.enable_av_recording``)
  and off by default; a table of its own can be migrated, queried and erased
  independently, without touching that column list at all.
* Privacy-by-construction: ``SessionUploader.upload()`` only ever sends
  ``subject_metadata`` (the ``M-IV/H-VII/...`` dict persisted via
  ``SessionMetadataSink``). A video path or transcript stored *inside* that
  dict would need its own hub-projection exclusion (``domain.hub_projection``)
  to stay off the hub. Kept in a table nothing in the upload path reads, an
  A/V recording cannot reach the hub by a future refactor forgetting to
  exclude it -- see the addendum, Section 2.5.

Follows :mod:`src.infrastructure.persistence.consent_repository`'s pattern:
self-contained ``CREATE TABLE IF NOT EXISTS`` in the constructor, not the
versioned ``migrations`` module -- that module's baselining logic exists for
``session_metadata``'s specific history and would be the wrong tool for a
table with no rows to baseline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.infrastructure.persistence.connection import transaction

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS av_recordings (
        session_id                     TEXT PRIMARY KEY,
        patient_id                     TEXT,
        consent_id                     TEXT,
        capture_backend                TEXT,
        video_path                     TEXT,
        transcript_path                TEXT,
        transcript_engine              TEXT,
        transcript_verified            INTEGER NOT NULL DEFAULT 0,
        raw_recording_deleted_at_utc   TEXT,
        pause_events_json              TEXT,
        started_at_utc                 TEXT,
        ended_at_utc                   TEXT,
        failure_reason                 TEXT,
        created_at_utc                 TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_av_recordings_patient ON av_recordings(patient_id)",
)


class AVRecordingRepository:
    """Reads and writes ``av_recordings``. One row per session."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        with transaction(self.db_path) as conn:
            for statement in _SCHEMA:
                conn.execute(statement)

    def create(self, record: dict[str, Any]) -> None:
        """Insert the row for a session's A/V recording, at capture start.

        Args:
            record: Must contain ``session_id`` and ``created_at_utc``; every
                other column defaults to NULL/0 and is filled in by
                :meth:`update` as capture, transcription and retention
                progress.
        """
        with transaction(self.db_path) as conn:
            conn.execute(
                """INSERT INTO av_recordings (
                       session_id, patient_id, consent_id, capture_backend,
                       started_at_utc, created_at_utc
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record["session_id"],
                    record.get("patient_id"),
                    record.get("consent_id"),
                    record.get("capture_backend"),
                    record.get("started_at_utc"),
                    record["created_at_utc"],
                ),
            )

    #: Columns :meth:`update` is allowed to write. A fixed whitelist rather
    #: than a free-form ``dict`` -> SQL builder, the same discipline
    #: ``DatabaseManager.QUESTIONNAIRE_FIELDS`` uses for exactly the same
    #: reason: this method's caller ultimately traces back to a capture
    #: backend and a transcription engine, not to a hand-typed column name.
    _UPDATABLE_FIELDS = (
        "video_path",
        "transcript_path",
        "transcript_engine",
        "transcript_verified",
        "raw_recording_deleted_at_utc",
        "pause_events_json",
        "ended_at_utc",
        "failure_reason",
    )

    def update(self, session_id: str, fields: dict[str, Any]) -> bool:
        """Merge ``fields`` into one session's row.

        Returns:
            Whether a row existed to update.

        Raises:
            ValueError: a key in ``fields`` is not in :data:`_UPDATABLE_FIELDS`.
        """
        unknown = set(fields) - set(self._UPDATABLE_FIELDS)
        if unknown:
            raise ValueError(f"Not updatable via AVRecordingRepository.update: {sorted(unknown)}")
        if not fields:
            return self.get(session_id) is not None

        columns = ", ".join(f"{key} = ?" for key in fields)
        with transaction(self.db_path) as conn:
            cursor = conn.execute(
                f"UPDATE av_recordings SET {columns} WHERE session_id = ?",  # noqa: S608 - keys checked above
                (*fields.values(), session_id),
            )
            return cursor.rowcount > 0

    def get(self, session_id: str) -> dict[str, Any] | None:
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM av_recordings WHERE session_id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        with transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM av_recordings WHERE patient_id = ? ORDER BY created_at_utc DESC",
                (patient_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_for_sessions(self, session_ids: list[str]) -> int:
        """Delete the rows for the given sessions. Used by right-to-erasure paths.

        Returns:
            How many rows were deleted -- reported to the participant as part
            of an erasure or a P-C7 withdrawal.
        """
        if not session_ids:
            return 0
        placeholders = ", ".join("?" * len(session_ids))
        with transaction(self.db_path) as conn:
            cursor = conn.execute(
                f"DELETE FROM av_recordings WHERE session_id IN ({placeholders})",  # noqa: S608 - placeholders only
                session_ids,
            )
            return cursor.rowcount

    def due_for_retention_sweep(self, cutoff_utc: str) -> list[dict[str, Any]]:
        """Rows whose video is still present, transcribed and verified, and old enough to delete.

        Args:
            cutoff_utc: ISO-8601 UTC timestamp. A row qualifies when
                ``ended_at_utc`` is at or before it.

        Returns:
            Rows for :func:`src.av_recording.retention.sweep_av_retention` to
            act on.
        """
        with transaction(self.db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM av_recordings
                   WHERE video_path IS NOT NULL
                     AND transcript_verified = 1
                     AND raw_recording_deleted_at_utc IS NULL
                     AND ended_at_utc IS NOT NULL
                     AND ended_at_utc <= ?""",
                (cutoff_utc,),
            ).fetchall()
        return [dict(r) for r in rows]
