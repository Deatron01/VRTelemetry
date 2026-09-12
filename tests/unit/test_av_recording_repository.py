# tests/unit/test_av_recording_repository.py
"""``av_recordings``: its own table, independent of session_metadata (VRT-22
is why -- see the module docstring in av_recording_repository.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.persistence.av_recording_repository import AVRecordingRepository


@pytest.fixture
def repo(tmp_path: Path) -> AVRecordingRepository:
    return AVRecordingRepository(tmp_path / "metadata.db")


def test_create_then_get_round_trips_the_row(repo: AVRecordingRepository):
    repo.create(
        {
            "session_id": "sess-1",
            "patient_id": "pat-1",
            "consent_id": "con-1",
            "capture_backend": "pc_compositor_mirror",
            "started_at_utc": "2026-09-12T00:00:00",
            "created_at_utc": "2026-09-12T00:00:00",
        }
    )

    row = repo.get("sess-1")
    assert row is not None
    assert row["session_id"] == "sess-1"
    assert row["patient_id"] == "pat-1"
    assert row["transcript_verified"] == 0
    assert row["video_path"] is None


def test_get_of_an_unknown_session_is_none(repo: AVRecordingRepository):
    assert repo.get("nope") is None


def test_update_merges_only_whitelisted_fields(repo: AVRecordingRepository):
    repo.create({"session_id": "sess-1", "created_at_utc": "t0"})

    assert repo.update("sess-1", {"video_path": "/x/vr_telemetry_sess-1.mp4"}) is True
    row = repo.get("sess-1")
    assert row["video_path"] == "/x/vr_telemetry_sess-1.mp4"

    with pytest.raises(ValueError, match="session_id"):
        repo.update("sess-1", {"session_id": "sess-2"})


def test_update_of_a_missing_row_reports_no_row(repo: AVRecordingRepository):
    assert repo.update("nope", {"failure_reason": "x"}) is False
    assert repo.update("nope", {}) is False


def test_list_for_patient_orders_newest_first(repo: AVRecordingRepository):
    repo.create({"session_id": "a", "patient_id": "pat-1", "created_at_utc": "2026-01-01T00:00:00"})
    repo.create({"session_id": "b", "patient_id": "pat-1", "created_at_utc": "2026-02-01T00:00:00"})
    repo.create({"session_id": "c", "patient_id": "pat-2", "created_at_utc": "2026-01-15T00:00:00"})

    rows = repo.list_for_patient("pat-1")
    assert [r["session_id"] for r in rows] == ["b", "a"]


def test_delete_for_sessions_removes_only_the_named_rows(repo: AVRecordingRepository):
    repo.create({"session_id": "a", "patient_id": "pat-1", "created_at_utc": "t0"})
    repo.create({"session_id": "b", "patient_id": "pat-1", "created_at_utc": "t0"})

    deleted = repo.delete_for_sessions(["a", "does-not-exist"])

    assert deleted == 1
    assert repo.get("a") is None
    assert repo.get("b") is not None


def test_delete_for_sessions_with_an_empty_list_deletes_nothing(repo: AVRecordingRepository):
    repo.create({"session_id": "a", "created_at_utc": "t0"})
    assert repo.delete_for_sessions([]) == 0
    assert repo.get("a") is not None


def test_due_for_retention_sweep_requires_video_verified_transcript_and_age(
    repo: AVRecordingRepository,
):
    # Not ended yet: excluded.
    repo.create({"session_id": "in-progress", "created_at_utc": "t0"})
    repo.update("in-progress", {"video_path": "/x/a.mp4"})

    # Ended, but never transcribed: excluded.
    repo.create({"session_id": "no-transcript", "created_at_utc": "t0"})
    repo.update("no-transcript", {"video_path": "/x/b.mp4", "ended_at_utc": "2026-01-01T00:00:00"})

    # Ended, transcribed, verified, old enough: included.
    repo.create({"session_id": "due", "created_at_utc": "t0"})
    repo.update(
        "due",
        {
            "video_path": "/x/c.mp4",
            "ended_at_utc": "2026-01-01T00:00:00",
            "transcript_verified": 1,
        },
    )

    # Same shape, but already swept: excluded.
    repo.create({"session_id": "already-swept", "created_at_utc": "t0"})
    repo.update(
        "already-swept",
        {
            "video_path": "/x/d.mp4",
            "ended_at_utc": "2026-01-01T00:00:00",
            "transcript_verified": 1,
            "raw_recording_deleted_at_utc": "2026-01-02T00:00:00",
        },
    )

    due = repo.due_for_retention_sweep("2026-06-01T00:00:00")
    assert [r["session_id"] for r in due] == ["due"]


def test_due_for_retention_sweep_respects_the_cutoff(repo: AVRecordingRepository):
    repo.create({"session_id": "too-recent", "created_at_utc": "t0"})
    repo.update(
        "too-recent",
        {
            "video_path": "/x/e.mp4",
            "ended_at_utc": "2026-06-15T00:00:00",
            "transcript_verified": 1,
        },
    )

    assert repo.due_for_retention_sweep("2026-06-01T00:00:00") == []
    due = repo.due_for_retention_sweep("2026-12-31T00:00:00")
    assert [r["session_id"] for r in due] == ["too-recent"]
