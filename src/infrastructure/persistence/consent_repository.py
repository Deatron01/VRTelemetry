# src/infrastructure/persistence/consent_repository.py
"""The consent register: append-only evidence of who agreed to what (GDPR-09).

Two tables in ``patients.db``, beside the patient records they refer to:

``consent_records``
    One row per consent given: the participant's pseudonymous id, the study,
    the wording version, every checkbox and the SHA-256 of the exact text shown
    for it, the researcher's confirmations, who supervised and on which
    workstation, and a hash of the participant's withdrawal code.

``consent_events``
    Everything that happens to consent afterwards -- given, withdrawn (with its
    scope), erased -- so the history can be reconstructed without trusting a
    log file to have been kept (Art. 5(2) GDPR; this is also most of what
    GDPR-04 asked for).

**Both tables are immutable, and SQLite enforces it.** ``BEFORE UPDATE`` and
``BEFORE DELETE`` triggers abort any attempt to change or remove a row. Evidence
that the application can quietly rewrite is not evidence. A withdrawal is a new
event, never an edit of the consent it withdraws, and erasing a participant's
data leaves these rows in place: they hold no name, only the pseudonymous id,
and they are what shows the recordings were lawful while they existed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.infrastructure.persistence.connection import transaction

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS consent_records (
        consent_id              TEXT PRIMARY KEY,
        patient_id              TEXT NOT NULL,
        study_id                TEXT NOT NULL,
        study_title             TEXT,
        text_version            TEXT NOT NULL,
        notice_version          TEXT NOT NULL,
        language                TEXT NOT NULL,
        method                  TEXT NOT NULL,
        choices_json            TEXT NOT NULL,
        text_sha256_json        TEXT NOT NULL,
        researcher_json         TEXT NOT NULL,
        researcher_user         TEXT,
        workstation             TEXT,
        withdrawal_code_sha256  TEXT NOT NULL,
        given_at_utc            TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_consent_records_patient ON consent_records(patient_id)",
    """
    CREATE TABLE IF NOT EXISTS consent_events (
        event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id      TEXT NOT NULL,
        consent_id      TEXT,
        event_type      TEXT NOT NULL,
        scope           TEXT,
        occurred_at_utc TEXT NOT NULL,
        detail          TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_consent_events_patient ON consent_events(patient_id)",
    *(
        f"""
        CREATE TRIGGER IF NOT EXISTS {table}_immutable_{verb.lower()}
        BEFORE {verb} ON {table}
        BEGIN
            SELECT RAISE(ABORT, '{table} is append-only: consent evidence cannot be changed');
        END
        """
        for table in ("consent_records", "consent_events")
        for verb in ("UPDATE", "DELETE")
    ),
)

#: Withdrawal scopes that end a consent's authority to record.
ENDING_SCOPES = ("ALL_DELETE", "FUTURE_ONLY")


class ConsentRepository:
    """Reads and appends consent evidence. Never updates, never deletes."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        with transaction(self.db_path) as conn:
            for statement in _SCHEMA:
                conn.execute(statement)

    # --- writes (append only) ---------------------------------------------

    def insert_consent(self, record: dict[str, Any]) -> None:
        """Append one consent. ``choices``, ``text_sha256`` and ``researcher`` are dicts."""
        with transaction(self.db_path) as conn:
            conn.execute(
                """INSERT INTO consent_records (
                       consent_id, patient_id, study_id, study_title, text_version,
                       notice_version, language, method, choices_json, text_sha256_json,
                       researcher_json, researcher_user, workstation,
                       withdrawal_code_sha256, given_at_utc
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["consent_id"],
                    record["patient_id"],
                    record["study_id"],
                    record.get("study_title"),
                    record["text_version"],
                    record["notice_version"],
                    record["language"],
                    record["method"],
                    json.dumps(record["choices"], sort_keys=True),
                    json.dumps(record["text_sha256"], sort_keys=True),
                    json.dumps(record["researcher"], sort_keys=True),
                    record.get("researcher_user"),
                    record.get("workstation"),
                    record["withdrawal_code_sha256"],
                    record["given_at_utc"],
                ),
            )
            conn.execute(
                """INSERT INTO consent_events
                       (patient_id, consent_id, event_type, scope, occurred_at_utc)
                   VALUES (?, ?, 'given', NULL, ?)""",
                (record["patient_id"], record["consent_id"], record["given_at_utc"]),
            )

    def insert_event(
        self,
        *,
        patient_id: str,
        event_type: str,
        occurred_at_utc: str,
        consent_id: str | None = None,
        scope: str | None = None,
        detail: str | None = None,
    ) -> None:
        with transaction(self.db_path) as conn:
            conn.execute(
                """INSERT INTO consent_events
                       (patient_id, consent_id, event_type, scope, occurred_at_utc, detail)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (patient_id, consent_id, event_type, scope, occurred_at_utc, detail),
            )

    # --- reads --------------------------------------------------------------

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["choices"] = json.loads(row.pop("choices_json"))
        row["text_sha256"] = json.loads(row.pop("text_sha256_json"))
        row["researcher"] = json.loads(row.pop("researcher_json"))
        return row

    def get(self, consent_id: str) -> dict[str, Any] | None:
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM consent_records WHERE consent_id = ?", (consent_id,)
            ).fetchone()
        return self._decode(row) if row else None

    def list_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        """Every consent the participant gave, newest first."""
        with transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM consent_records WHERE patient_id = ? "
                "ORDER BY given_at_utc DESC, rowid DESC",
                (patient_id,),
            ).fetchall()
        return [self._decode(r) for r in rows]

    def find_by_withdrawal_code_hash(self, code_sha256: str) -> dict[str, Any] | None:
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM consent_records WHERE withdrawal_code_sha256 = ?", (code_sha256,)
            ).fetchone()
        return self._decode(row) if row else None

    def events_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        with transaction(self.db_path) as conn:
            return list(
                conn.execute(
                    "SELECT * FROM consent_events WHERE patient_id = ? ORDER BY event_id",
                    (patient_id,),
                ).fetchall()
            )

    def is_ended(self, consent_id: str) -> bool:
        """Whether a withdrawal has ended this consent's authority to record."""
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM consent_events WHERE consent_id = ? AND event_type = 'withdrawn' "
                "AND scope IN ('ALL_DELETE', 'FUTURE_ONLY') LIMIT 1",
                (consent_id,),
            ).fetchone()
        return row is not None

    def is_research_withdrawn(self, consent_id: str) -> bool:
        """Whether the optional provider-research consent was withdrawn separately."""
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM consent_events WHERE consent_id = ? "
                "AND event_type = 'research_withdrawn' LIMIT 1",
                (consent_id,),
            ).fetchone()
        return row is not None
