# src/application/erasure.py
"""Erasing a participant, everywhere their data is (GDPR-10).

Before this, ``DELETE /api/patients/{id}`` -- the right-to-erasure button --
blanked the name, date of birth, notes and health fields on the patient row
and stopped there. Every recording stayed: the Parquet files on the
workstation, their ``session_metadata`` rows, their session logs, and every
copy already uploaded to the hub, all still linked to the same ``patient_id``.
The participant's eye movements, pupil sizes and heart rate outlived the
erasure of their name.

Erasure now means, in this order:

1. refuse if the participant is being recorded at this moment;
2. delete the workstation's files for every one of their sessions -- raw and
   derived Parquet, and session logs. If any file cannot be deleted, stop
   *before* touching the database, so nothing is left behind that the
   backfill sweep would later upload with no owner attached;
3. drop their queued uploads, so nothing already in the queue is sent after
   the fact;
4. delete their ``session_metadata`` rows;
5. anonymise (or, with ``hard_delete``, remove) the patient row;
6. append an ``erased`` event to their consent history -- the consent
   evidence itself stays, holding only the pseudonymous id, because it is
   what shows the recordings were lawful while they existed;
7. ask the hub to delete its copies, queueing the request if the hub cannot
   be reached right now.

What this does not reach, and says so: recordings written to a custom
``output_dir`` outside the configured sessions directory, and copies anyone
exported by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.application.consent import ConsentService


class ErasureBlockedError(RuntimeError):
    """The erasure cannot run right now; nothing has been changed."""


class _Patients(Protocol):
    def get_patient(self, patient_id: str) -> dict[str, Any] | None: ...

    def delete_patient(self, patient_id: str, hard_delete: bool = False) -> bool: ...


class _Sessions(Protocol):
    def session_ids_for_patient(self, patient_id: str) -> list[str]: ...

    def delete_sessions(self, session_ids: list[str]) -> int: ...


class _AVRecordings(Protocol):
    """The A/V-recording metadata rows this service needs to clear (P-C7).

    Separate from ``_Sessions`` because ``av_recordings`` rows are the A/V
    pipeline's own table (``src.infrastructure.persistence.av_recording_repository``),
    not ``session_metadata`` -- deleting a participant's video/transcript must
    not touch their telemetry row, and the reverse.
    """

    def delete_for_sessions(self, session_ids: list[str]) -> int: ...


class _Queues(Protocol):
    def clear_pending_upload(self, session_id: str) -> None: ...

    def clear_pending_session_log(self, session_id: str) -> None: ...


class _Hub(Protocol):
    def request_erasure(self, patient_id: str, session_ids: list[str]) -> dict[str, Any]: ...


@dataclass
class ErasureReport:
    """What an erasure removed, for the response and the consent history."""

    patient_id: str
    session_ids: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    metadata_rows_deleted: int = 0
    hub: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "sessions": len(self.session_ids),
            "files_deleted": len(self.files_deleted),
            "metadata_rows_deleted": self.metadata_rows_deleted,
            "hub_confirmed": bool(self.hub.get("ok")),
            "hub_queued": bool(self.hub.get("queued")),
        }


class ErasureService:
    """Carries out a participant's right to erasure across workstation and hub."""

    def __init__(
        self,
        *,
        patients: _Patients,
        sessions: _Sessions,
        consents: ConsentService,
        queues: _Queues,
        hub: _Hub,
        sessions_dir: Path,
        session_logs_dir: Path,
        is_recording_patient: Callable[[str], bool],
        av_recordings: _AVRecordings | None = None,
    ) -> None:
        self.patients = patients
        self.sessions = sessions
        self.consents = consents
        self.queues = queues
        self.hub = hub
        self.sessions_dir = Path(sessions_dir)
        self.session_logs_dir = Path(session_logs_dir)
        self.is_recording_patient = is_recording_patient
        #: None on an install that predates the A/V recording feature, or in a
        #: test that does not exercise it -- ``erase()``'s file glob covers the
        #: A/V artifacts regardless, so a full erasure loses nothing either
        #: way. Only the targeted SPEECH_RECORDING_ONLY path
        #: (:meth:`erase_av_recordings`) needs the row cleared, and it is a
        #: no-op without this.
        self.av_recordings = av_recordings

    def _files_for(self, session_id: str) -> list[Path]:
        """Every workstation file belonging to one session.

        ``vr_telemetry_<id>*.parquet`` covers the raw recording and the
        ``_ai_ready`` derivative the preprocessor writes beside it.
        ``*.mp4`` and ``*.transcript.json`` are the A/V recording's video and
        transcript (P-C7, addendum Section 2.4/2.5) -- never uploaded to the
        hub (see ``src.av_recording.session_recorder``), so deleting them here
        is the only place they are erased at all.
        """
        files = list(self.sessions_dir.glob(f"vr_telemetry_{session_id}*.parquet"))
        files += list(self.sessions_dir.glob(f"vr_telemetry_{session_id}*.mp4"))
        files += list(self.sessions_dir.glob(f"vr_telemetry_{session_id}*.transcript.json"))
        files += list(self.session_logs_dir.glob(f"session_{session_id}*.log"))
        return files

    def _av_files_for(self, session_id: str) -> list[Path]:
        """Only the A/V artifacts for one session -- for the targeted withdrawal scope."""
        files = list(self.sessions_dir.glob(f"vr_telemetry_{session_id}*.mp4"))
        files += list(self.sessions_dir.glob(f"vr_telemetry_{session_id}*.transcript.json"))
        return files

    def erase(self, patient_id: str, *, hard_delete: bool = False) -> ErasureReport:
        """Erase one participant. See the module docstring for the order and why.

        Raises:
            LookupError: the patient does not exist.
            ErasureBlockedError: the participant is being recorded, or a file
                could not be deleted. In the second case the files that could be
                deleted are gone and the rest -- database included -- is
                untouched, so the erasure can simply be requested again.
        """
        if self.patients.get_patient(patient_id) is None:
            raise LookupError(patient_id)
        if self.is_recording_patient(patient_id):
            raise ErasureBlockedError(
                "This participant is being recorded right now. Stop the recording first."
            )

        report = ErasureReport(patient_id=patient_id)
        report.session_ids = self.sessions.session_ids_for_patient(patient_id)

        locked: list[str] = []
        for session_id in report.session_ids:
            for path in self._files_for(session_id):
                try:
                    path.unlink()
                    report.files_deleted.append(path.name)
                except FileNotFoundError:
                    continue
                except OSError:
                    locked.append(path.name)
        if locked:
            raise ErasureBlockedError(
                f"Could not delete {len(locked)} file(s), most likely because another program "
                f"has them open: {', '.join(sorted(locked))}. Close it and erase again; nothing "
                f"else has been changed."
            )

        for session_id in report.session_ids:
            self.queues.clear_pending_upload(session_id)
            self.queues.clear_pending_session_log(session_id)
        report.metadata_rows_deleted = self.sessions.delete_sessions(report.session_ids)
        self.patients.delete_patient(patient_id, hard_delete=hard_delete)

        report.hub = self.hub.request_erasure(patient_id, report.session_ids)
        summary = report.as_dict()
        self.consents.record_erasure(
            patient_id,
            detail=(
                f"sessions={summary['sessions']} files={summary['files_deleted']} "
                f"hub={'confirmed' if summary['hub_confirmed'] else 'queued'}"
            ),
        )
        return report

    def erase_av_recordings(self, patient_id: str) -> ErasureReport:
        """Delete only a participant's A/V recordings, transcripts and derived scores.

        The workstation counterpart of
        ``WithdrawalScope.SPEECH_RECORDING_ONLY`` (addendum Section 3.4): the
        video, transcript and any stored derived score are removed for every
        session; the Parquet telemetry, session metadata and consent record
        are untouched, because the participant withdrew only P-C7, not their
        whole consent.

        Never uploaded to the hub in the first place (see
        ``src.av_recording.session_recorder``), so there is no hub request
        here -- unlike :meth:`erase`, this never reaches the network.

        Raises:
            LookupError: the patient does not exist.
            ErasureBlockedError: the participant is being recorded right now,
                or a file could not be deleted (nothing else is changed in
                that case; retry once the lock clears).
        """
        if self.patients.get_patient(patient_id) is None:
            raise LookupError(patient_id)
        if self.is_recording_patient(patient_id):
            raise ErasureBlockedError(
                "This participant is being recorded right now. Stop the recording first."
            )

        report = ErasureReport(patient_id=patient_id)
        report.session_ids = self.sessions.session_ids_for_patient(patient_id)

        locked: list[str] = []
        for session_id in report.session_ids:
            for path in self._av_files_for(session_id):
                try:
                    path.unlink()
                    report.files_deleted.append(path.name)
                except FileNotFoundError:
                    continue
                except OSError:
                    locked.append(path.name)
        if locked:
            raise ErasureBlockedError(
                f"Could not delete {len(locked)} file(s), most likely because another program "
                f"has them open: {', '.join(sorted(locked))}. Close it and withdraw again; "
                f"nothing else has been changed."
            )

        if self.av_recordings is not None:
            report.metadata_rows_deleted = self.av_recordings.delete_for_sessions(
                report.session_ids
            )

        summary = report.as_dict()
        self.consents.record_erasure(
            patient_id,
            detail=(
                f"scope=SPEECH_RECORDING_ONLY sessions={summary['sessions']} "
                f"files={summary['files_deleted']}"
            ),
        )
        return report
