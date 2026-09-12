# tests/unit/test_av_recording_retention.py
"""Storage limitation for A/V recordings (Art. 5(1)(e) GDPR, addendum 2.4)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from src.av_recording.retention import sweep_av_retention
from src.infrastructure.persistence.av_recording_repository import AVRecordingRepository
from src.utils.clock import as_stored, utc_now


@pytest.fixture
def repo(tmp_path: Path) -> AVRecordingRepository:
    return AVRecordingRepository(tmp_path / "metadata.db")


def _due_row(
    repo: AVRecordingRepository, session_id: str, video_path: Path, ended_ago_days: int
) -> None:
    video_path.write_bytes(b"video")
    repo.create({"session_id": session_id, "created_at_utc": "t0"})
    ended_at = as_stored(utc_now() - timedelta(days=ended_ago_days))
    repo.update(
        session_id,
        {
            "video_path": str(video_path),
            "ended_at_utc": ended_at,
            "transcript_verified": 1,
        },
    )


def test_a_verified_recording_past_the_default_zero_day_retention_is_deleted_immediately(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    video = tmp_path / "vr_telemetry_sess-1.mp4"
    _due_row(repo, "sess-1", video, ended_ago_days=1)

    result = sweep_av_retention(repo, retention_days=0)

    assert result == {"checked": 1, "deleted": 1}
    assert not video.exists()
    row = repo.get("sess-1")
    assert row["raw_recording_deleted_at_utc"] is not None
    assert row["transcript_path"] is None  # untouched -- only the video is ever deleted


def test_nothing_due_is_a_safe_no_op(repo: AVRecordingRepository) -> None:
    assert sweep_av_retention(repo, retention_days=0) == {"checked": 0, "deleted": 0}


def test_a_configured_retention_window_delays_deletion(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    video = tmp_path / "vr_telemetry_sess-1.mp4"
    _due_row(repo, "sess-1", video, ended_ago_days=1)

    result = sweep_av_retention(repo, retention_days=30)

    assert result == {"checked": 0, "deleted": 0}
    assert video.exists()


def test_a_missing_file_on_disk_still_marks_the_row_swept(
    repo: AVRecordingRepository, tmp_path: Path
) -> None:
    """The row can be due even if the file is already gone by hand -- the
    sweep must not treat that as an error that blocks marking it swept."""
    video = tmp_path / "vr_telemetry_sess-1.mp4"
    _due_row(repo, "sess-1", video, ended_ago_days=1)
    video.unlink()

    result = sweep_av_retention(repo, retention_days=0)

    assert result == {"checked": 1, "deleted": 1}
    assert repo.get("sess-1")["raw_recording_deleted_at_utc"] is not None


def test_a_swept_recording_is_not_swept_again(repo: AVRecordingRepository, tmp_path: Path) -> None:
    video = tmp_path / "vr_telemetry_sess-1.mp4"
    _due_row(repo, "sess-1", video, ended_ago_days=1)

    sweep_av_retention(repo, retention_days=0)
    second = sweep_av_retention(repo, retention_days=0)

    assert second == {"checked": 0, "deleted": 0}
