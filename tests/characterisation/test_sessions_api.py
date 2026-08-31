"""Characterisation of the session, telemetry and questionnaire routes (VRT-9).

Covers 7 of the 29 routes on the workstation API:

    GET  /api/sessions
    GET  /api/sessions/{id}
    PUT  /api/sessions/{id}
    GET  /api/sessions/{id}/telemetry
    POST /api/sessions/{id}/questionnaire
    POST /api/upload-telemetry
    GET  /api/patients/{id}/sessions

These record today's behaviour so VRT-10 (router split) and VRT-11 (repository
layer) can prove they changed nothing. Where the behaviour is wrong, the test
pins the wrongness and names the ticket.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------- #
# GET /api/sessions
# --------------------------------------------------------------------------- #


def test_list_sessions_is_empty_before_any_recording(client: TestClient) -> None:
    response = client.get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == []


def test_list_sessions_returns_the_recorded_session(client: TestClient, session_row: str) -> None:
    response = client.get("/api/sessions")

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_row
    assert sessions[0]["subject_id"] == "SUB_TEST_01"


def test_list_sessions_projects_a_fixed_column_subset(client: TestClient, session_row: str) -> None:
    """The listing selects eight named columns, not SELECT *.

    Pinned because the frontend's session table reads exactly these keys; a
    router split that widened or narrowed the projection would break it
    silently rather than loudly.
    """
    row = client.get("/api/sessions").json()[0]

    assert set(row) == {
        "session_id",
        "patient_id",
        "start_timestamp_utc",
        "subject_id",
        "hmd_model",
        "tracking_space_type",
        "total_dropped_frames",
        "session_rating",
        "patient_display_name",
    }


def test_list_sessions_enriches_with_the_patient_display_name(
    client: TestClient, session_row: str
) -> None:
    assert client.get("/api/sessions").json()[0]["patient_display_name"] == "Test Subject"


def test_list_sessions_shows_erased_patients_as_a_placeholder(
    client: TestClient, workstation: Any, patient: dict[str, Any], session_row: str
) -> None:
    """An erased patient must not take their sessions out of the listing.

    Right-to-erasure anonymises the patient record; the session it produced is
    research data that still exists and still needs to be visible.
    """
    workstation.patients.delete_patient(patient["patient_id"], hard_delete=False)

    assert client.get("/api/sessions").json()[0]["patient_display_name"] == "[Erased Patient]"


# --------------------------------------------------------------------------- #
# GET /api/sessions/{id}
# --------------------------------------------------------------------------- #


def test_get_session_returns_the_full_row(client: TestClient, session_row: str) -> None:
    response = client.get(f"/api/sessions/{session_row}")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_row
    # Unlike the listing, this one is SELECT *, so it carries the wide schema.
    assert len(body) > 20


def test_get_unknown_session_is_404(client: TestClient) -> None:
    response = client.get("/api/sessions/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


# --------------------------------------------------------------------------- #
# PUT /api/sessions/{id}
# --------------------------------------------------------------------------- #


def test_update_session_writes_only_the_supplied_fields(
    client: TestClient, session_row: str
) -> None:
    response = client.put(f"/api/sessions/{session_row}", json={"session_rating": 4})

    assert response.status_code == 200
    assert response.json() == {"status": "success", "updated_fields": ["session_rating"]}
    assert client.get(f"/api/sessions/{session_row}").json()["session_rating"] == 4


def test_update_session_with_an_empty_body_is_a_no_op(client: TestClient, session_row: str) -> None:
    response = client.put(f"/api/sessions/{session_row}", json={})

    assert response.status_code == 200
    assert response.json() == {"status": "no changes"}


def test_update_session_cannot_clear_a_field(client: TestClient, session_row: str) -> None:
    """Explicit null is indistinguishable from omitted -- a real limitation.

    The handler filters on ``v is not None``, so there is no way through this
    API to clear a value once set. Pinning it as current behaviour; the fix is a
    sentinel or ``model_dump(exclude_unset=True)``, which belongs with the
    schema work in VRT-10.
    """
    client.put(f"/api/sessions/{session_row}", json={"session_rating": 4})

    response = client.put(f"/api/sessions/{session_row}", json={"session_rating": None})

    assert response.json() == {"status": "no changes"}
    assert client.get(f"/api/sessions/{session_row}").json()["session_rating"] == 4


def test_update_unknown_session_is_404(client: TestClient) -> None:
    response = client.put("/api/sessions/does-not-exist", json={"session_rating": 3})

    assert response.status_code == 404


def test_update_session_rejects_unknown_fields_at_the_schema_boundary(
    client: TestClient, session_row: str
) -> None:
    """Pydantic drops unmodelled keys, so an unknown field is silently ignored.

    That is what stops the f-string SET clause in the handler from becoming an
    injection vector: column names can only ever come from SessionUpdate's own
    field names. VRT-11 makes the allowlist explicit instead of implicit, which
    is where a reader can actually see the guarantee.
    """
    response = client.put(
        f"/api/sessions/{session_row}",
        json={"session_rating": 2, "subject_id = 'x'; DROP TABLE session_metadata; --": 1},
    )

    assert response.status_code == 200
    assert response.json()["updated_fields"] == ["session_rating"]
    assert client.get("/api/sessions").status_code == 200  # table intact


# --------------------------------------------------------------------------- #
# GET /api/sessions/{id}/telemetry
# --------------------------------------------------------------------------- #


def test_get_telemetry_returns_frames_and_the_session_record(
    client: TestClient, session_row: str, parquet_for_session: Path
) -> None:
    response = client.get(f"/api/sessions/{session_row}/telemetry")

    assert response.status_code == 200
    body = response.json()
    assert body["original_frames"] == 10
    assert len(body["frames"]) == 10
    assert "timestamp_ns" in body["columns"]
    assert body["session_record"]["session_id"] == session_row


def test_get_telemetry_rebases_timestamps_to_zero(
    client: TestClient, session_row: str, parquet_for_session: Path
) -> None:
    """Absolute nanosecond timestamps exceed JavaScript's safe integer range.

    The route subtracts the first frame's timestamp so the browser receives
    small offsets. This is load-bearing for the frontend and must survive the
    refactor.
    """
    frames = client.get(f"/api/sessions/{session_row}/telemetry").json()["frames"]

    assert frames[0]["timestamp_ns"] == 0
    assert frames[-1]["timestamp_ns"] == 9 * 8_333_333


def test_get_telemetry_for_unknown_session_is_404(client: TestClient) -> None:
    response = client.get("/api/sessions/nope/telemetry")

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_get_telemetry_distinguishes_a_missing_file_from_a_missing_session(
    client: TestClient, session_row: str
) -> None:
    """A recorded session whose Parquet has been moved or deleted says so.

    Both cases are 404, but the messages differ, and that difference is the only
    thing telling a researcher whether they have lost a file or mistyped an id.
    """
    response = client.get(f"/api/sessions/{session_row}/telemetry")

    assert response.status_code == 404
    assert "Parquet file is missing" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# POST /api/upload-telemetry
# --------------------------------------------------------------------------- #


def test_upload_telemetry_parses_an_uploaded_parquet(
    client: TestClient, parquet_for_session: Path
) -> None:
    with parquet_for_session.open("rb") as handle:
        response = client.post(
            "/api/upload-telemetry",
            files={"file": ("session.parquet", handle.read(), "application/octet-stream")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["original_frames"] == 10
    assert body["frames"][0]["timestamp_ns"] == 0
    assert set(body) == {"original_frames", "columns", "frames"}


def test_upload_telemetry_and_stored_telemetry_agree(
    client: TestClient, session_row: str, parquet_for_session: Path
) -> None:
    """The drag-drop path and the browse path must produce identical shapes.

    ``TelemetryParser.processData()`` in the frontend consumes both. They are
    two hand-copied implementations of the same downsampling today, which is
    exactly the kind of duplication that drifts; this test is what will catch it
    when VRT-10 unifies them.
    """
    stored = client.get(f"/api/sessions/{session_row}/telemetry").json()
    with parquet_for_session.open("rb") as handle:
        uploaded = client.post(
            "/api/upload-telemetry",
            files={"file": ("s.parquet", handle.read(), "application/octet-stream")},
        ).json()

    assert uploaded["columns"] == stored["columns"]
    assert uploaded["frames"] == stored["frames"]


def test_upload_telemetry_rejects_a_non_parquet_body(client: TestClient) -> None:
    """Current behaviour: pandas raises and FastAPI turns it into a 500.

    Documented, not endorsed -- a malformed upload is a client error and should
    be a 400. VRT-13 introduces the exception hierarchy and handlers that make
    that possible without a try/except in every route.
    """
    with pytest.raises(Exception):  # noqa: B017 - the point is that it escapes unhandled
        client.post(
            "/api/upload-telemetry",
            files={"file": ("notes.txt", io.BytesIO(b"not a parquet file"), "text/plain")},
        )


# --------------------------------------------------------------------------- #
# POST /api/sessions/{id}/questionnaire
# --------------------------------------------------------------------------- #


def test_questionnaire_scores_and_persists(client: TestClient, session_row: str) -> None:
    response = client.post(
        f"/api/sessions/{session_row}/questionnaire",
        json={
            "general_discomfort": 2,
            "nausea": 3,
            "eye_strain": 1,
            "mental_demand": 60.0,
            "effort": 55.0,
            "thermal_comfort": "neutral",
            "session_rating": 4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["ssq"]["ssq_total_severity"] > 0
    assert body["ssq"]["ssq_severity_band"]
    assert body["nasa_tlx"]["nasa_tlx_rtlx"] > 0

    stored = client.get(f"/api/sessions/{session_row}").json()
    assert stored["session_rating"] == 4
    assert stored["thermal_comfort"] == "neutral"


def test_questionnaire_treats_a_partial_form_as_zeros(client: TestClient, session_row: str) -> None:
    """Every field is optional, so a partially-completed form still submits.

    Deliberate: a defensible partial record beats an all-or-nothing form that a
    researcher abandons.
    """
    response = client.post(f"/api/sessions/{session_row}/questionnaire", json={"nausea": 1})

    assert response.status_code == 200
    assert response.json()["ssq"]["ssq_total_severity"] > 0


def test_questionnaire_for_unknown_session_is_404(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/questionnaire", json={"nausea": 1}).status_code == 404


def test_questionnaire_is_refused_after_consent_withdrawal(
    client: TestClient, workstation: Any, patient: dict[str, Any], session_row: str
) -> None:
    """New special-category health data must not be accepted against a
    withdrawn patient -- the same rule as starting a new recording."""
    workstation.patients.withdraw_consent(patient["patient_id"])

    response = client.post(f"/api/sessions/{session_row}/questionnaire", json={"nausea": 2})

    assert response.status_code == 403
    assert "withdrawn or erased GDPR consent" in response.json()["detail"]


def test_questionnaire_survives_an_unreachable_central_server(
    client: TestClient, session_row: str
) -> None:
    """The local record is authoritative; the re-sync is best-effort.

    The whole suite runs with the central server stubbed unreachable, so this
    passing at all is the assertion -- stated explicitly because it is a
    deliberate design property, not an accident.
    """
    assert (
        client.post(f"/api/sessions/{session_row}/questionnaire", json={"nausea": 1}).status_code
        == 200
    )


def test_questionnaire_rejects_a_non_numeric_score(client: TestClient, session_row: str) -> None:
    response = client.post(f"/api/sessions/{session_row}/questionnaire", json={"nausea": "very"})

    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# GET /api/patients/{id}/sessions
# --------------------------------------------------------------------------- #


def test_patient_sessions_returns_patient_and_their_sessions(
    client: TestClient, patient: dict[str, Any], session_row: str
) -> None:
    response = client.get(f"/api/patients/{patient['patient_id']}/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["patient"]["patient_id"] == patient["patient_id"]
    assert [s["session_id"] for s in body["sessions"]] == [session_row]


def test_patient_sessions_for_unknown_patient_is_404(client: TestClient) -> None:
    assert client.get("/api/patients/nope/sessions").status_code == 404
