"""Characterisation of the recording, live-state, sync, auth, licence and config
routes (VRT-9).

Covers the remaining 17 routes:

    POST /api/recording/start          POST /api/recording/stop
    POST /api/session/scene            POST /api/session/mark
    POST /api/session/haptic           POST /api/session/target
    GET  /api/sync/status              POST /api/sync/retry
    POST /api/sync/backfill
    POST /api/auth/register            POST /api/auth/login
    POST /api/auth/logout              GET  /api/auth/session
    GET  /api/license/status           POST /api/license/activate
    GET  /api/config/central-server    POST /api/config/central-server

Recording is never actually started here. ``/api/recording/start`` spawns a
daemon thread that binds VR hardware; the useful and testable behaviour is
everything it refuses to do, which is also the part carrying the GDPR rules.
Exercising a real recording belongs in the hardware-marked suite.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

START_BODY = {
    "patient_id": "",
    "subject_id": "SUB_TEST_01",
    "backend": "auto",
    "gdpr_consent": True,
}


# --------------------------------------------------------------------------- #
# Recording lifecycle -- the refusals
# --------------------------------------------------------------------------- #


def test_recording_start_requires_consent_on_the_request(
    client: TestClient, patient: dict[str, Any]
) -> None:
    response = client.post(
        "/api/recording/start",
        json={**START_BODY, "patient_id": patient["patient_id"], "gdpr_consent": False},
    )

    assert response.status_code == 403
    assert "GDPR consent" in response.json()["detail"]


def test_recording_start_requires_a_known_patient(client: TestClient) -> None:
    response = client.post("/api/recording/start", json={**START_BODY, "patient_id": "nope"})

    assert response.status_code == 404


def test_recording_start_is_refused_after_consent_withdrawal(
    client: TestClient, workstation: Any, patient: dict[str, Any]
) -> None:
    """Consent withdrawn on the patient record outranks consent asserted in the request.

    The request body's `gdpr_consent` is the operator confirming they have
    consent; the patient record is the system's own memory of it. When they
    disagree, the record wins.
    """
    workstation._patients.withdraw_consent(patient["patient_id"])

    response = client.post(
        "/api/recording/start", json={**START_BODY, "patient_id": patient["patient_id"]}
    )

    assert response.status_code == 403
    assert "consent is not active" in response.json()["detail"]


def test_recording_start_is_refused_for_an_erased_patient(
    client: TestClient, workstation: Any, patient: dict[str, Any]
) -> None:
    workstation._patients.delete_patient(patient["patient_id"], hard_delete=False)

    response = client.post(
        "/api/recording/start", json={**START_BODY, "patient_id": patient["patient_id"]}
    )

    assert response.status_code == 404


def test_recording_stop_without_an_active_session_is_400(client: TestClient) -> None:
    response = client.post("/api/recording/stop")

    assert response.status_code == 400
    assert response.json()["detail"] == "No active recording to stop."


# --------------------------------------------------------------------------- #
# Live experiment state -- all four require an active engine
# --------------------------------------------------------------------------- #


def test_live_state_routes_require_an_active_recording(client: TestClient) -> None:
    """Four routes, one guard. Pinned together because VRT-10 splits them apart."""
    for path, body in [
        ("/api/session/scene", {"scene_id": 2.0}),
        ("/api/session/mark", {"value": 1.0}),
        ("/api/session/haptic", {"side": "left", "intensity": 0.5}),
        ("/api/session/target", {"x": 0.0, "y": 1.0, "z": -0.5}),
    ]:
        response = client.post(path, json=body)
        assert response.status_code == 400, path
        assert response.json()["detail"] == "No active recording session."


def test_haptic_validates_the_side_before_the_engine_guard(client: TestClient) -> None:
    """Ordering detail worth pinning: a bad `side` is 400 for a different reason.

    Both are 400 today, so the distinction is invisible in the status code and
    lives only in the message. VRT-13's exception hierarchy is what makes these
    two failures tell themselves apart.
    """
    response = client.post("/api/session/haptic", json={"side": "middle", "intensity": 0.5})

    assert response.status_code == 400
    assert "side must be" in response.json()["detail"]


def test_live_state_routes_validate_their_bodies(client: TestClient) -> None:
    assert client.post("/api/session/scene", json={}).status_code == 422
    assert client.post("/api/session/target", json={"x": 0.0}).status_code == 422


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #


def test_sync_status_reports_empty_queues_and_stopped_threads(client: TestClient) -> None:
    """The background threads are not running because lifespan was not started.

    That is the point of the fixture, and it makes this the honest reading of a
    freshly-imported process rather than one mid-flight.
    """
    body = client.get("/api/sync/status").json()

    assert body["pending_count"] == 0
    assert body["pending_sessions"] == 0
    assert body["pending_logs"] == 0
    assert body["pending_patients"] == 0
    assert body["background_sync_running"] is False
    assert body["heartbeat_running"] is False
    assert body["pending"] == []


def test_sync_retry_sweeps_and_reports_rather_than_raising(client: TestClient) -> None:
    """ "Sync Now" against an unreachable server must report, not error."""
    response = client.post("/api/sync/retry")

    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_sync_backfill_scans_and_reports(client: TestClient) -> None:
    response = client.post("/api/sync/backfill")

    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_sync_status_counts_a_queued_upload(client: TestClient, workstation: Any) -> None:
    """A queued item must show up in the count the UI badges."""
    workstation._local_cache.queue_pending_upload("20260527_133428", "s.parquet", "{}")

    body = client.get("/api/sync/status").json()

    assert body["pending_sessions"] == 1
    assert body["pending_count"] == 1
    assert body["pending"][0]["session_id"] == "20260527_133428"


# --------------------------------------------------------------------------- #
# Auth -- every route is a proxy to the central server
# --------------------------------------------------------------------------- #


def test_auth_register_reports_an_unreachable_server_as_502(client: TestClient) -> None:
    """502 not 500: the workstation is fine, its upstream is not.

    Worth pinning because it is the difference between a researcher checking
    their network and a researcher filing a bug.
    """
    response = client.post(
        "/api/auth/register",
        json={"email": "a@example.test", "password": "hunter22", "org_name": "Lab"},
    )

    assert response.status_code == 502
    assert "Cannot reach central server" in response.json()["detail"]


def test_auth_login_reports_an_unreachable_server_as_502(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "a@example.test", "password": "hunter22"}
    )

    assert response.status_code == 502


def test_auth_session_reports_unauthenticated_when_no_session_is_cached(client: TestClient) -> None:
    assert client.get("/api/auth/session").json() == {"authenticated": False}


def test_auth_session_trusts_the_local_cache_when_the_server_is_unreachable(
    client: TestClient, workstation: Any
) -> None:
    """A LAN blip mid-recording must not eject the researcher from the app.

    Deliberate design, and exactly the sort of property that a refactor
    "simplifies" away without noticing. The `offline: True` flag is how the UI
    knows to show a degraded state rather than a normal one.
    """
    workstation._local_cache.save_session("tok-123", "user-1", "a@example.test", "Researcher A")

    body = client.get("/api/auth/session").json()

    assert body["authenticated"] is True
    assert body["offline"] is True
    assert body["email"] == "a@example.test"


def test_auth_logout_clears_local_state_even_when_the_server_is_unreachable(
    client: TestClient, workstation: Any
) -> None:
    """Logging out must always work locally. A user asking to be logged out is
    not making a request that a network failure may decline."""
    workstation._local_cache.save_session("tok-123", "user-1", "a@example.test", "Researcher A")

    assert client.post("/api/auth/logout").json() == {"ok": True}
    assert client.get("/api/auth/session").json() == {"authenticated": False}


# --------------------------------------------------------------------------- #
# Licence
# --------------------------------------------------------------------------- #


def test_license_status_is_not_activated_on_a_clean_install(client: TestClient) -> None:
    assert client.get("/api/license/status").json() == {"activated": False}


def test_license_activate_reports_an_unreachable_server_as_502(client: TestClient) -> None:
    response = client.post("/api/license/activate", json={"license_key": "AAAA-BBBB-CCCC-DDDD"})

    assert response.status_code == 502


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_central_server_url_is_empty_until_configured(client: TestClient) -> None:
    """Changed deliberately by VRT-6, and this test is how it was noticed.

    It previously asserted a default of "http://127.0.0.1:9000". That default
    was a guess: an install that had never been configured would silently aim
    every upload at a hub on its own machine, which does not exist, and report
    a connection error rather than "you have not set a server address".

    There is now no default. Empty means unset, which the app can show as such.
    The sibling literal in the old code was worse still --
    "http://192.168.1.X:9000", a placeholder with a letter where an octet
    belongs, shipping as a live value in two places. Settings now rejects that
    string outright.
    """
    assert client.get("/api/config/central-server").json() == {"central_server_url": ""}


def test_a_configured_url_is_returned_and_used(client: TestClient) -> None:
    """Setting one works exactly as before; only the unset case changed."""
    client.post("/api/config/central-server", json={"central_server_url": "http://10.0.0.9:9000"})

    assert client.get("/api/config/central-server").json() == {
        "central_server_url": "http://10.0.0.9:9000"
    }


def test_central_server_url_round_trips_through_the_local_cache(client: TestClient) -> None:
    new_url = "http://192.168.1.50:9000"

    assert client.post(
        "/api/config/central-server", json={"central_server_url": new_url}
    ).json() == {
        "ok": True,
        "central_server_url": new_url,
    }
    assert client.get("/api/config/central-server").json()["central_server_url"] == new_url


def test_changing_the_central_url_does_not_repoint_the_live_uploader(
    client: TestClient, workstation: Any
) -> None:
    """A real wart, pinned as current behaviour.

    `_session_uploader` and `_patient_uploader` are constructed at import time
    with `_central_url()` evaluated once. Changing the URL through this route
    updates the cache and every subsequent `_central_url()` call, but the two
    long-lived uploaders keep the address they were born with until the process
    restarts. A researcher who corrects a mistyped server address and does not
    restart will watch uploads keep failing against the old one.

    Not fixed here -- it is a symptom of import-time construction, which VRT-12
    removes wholesale. This test documents the current behaviour and will need
    inverting when it does.
    """
    original = workstation._session_uploader.central_server_url

    client.post("/api/config/central-server", json={"central_server_url": "http://10.0.0.9:9000"})

    assert workstation._central_url() == "http://10.0.0.9:9000"
    assert workstation._session_uploader.central_server_url == original


def test_the_offline_stub_is_actually_in_force(client: TestClient, workstation: Any) -> None:
    """Guards the fixture itself, not the application.

    Every "unreachable server" assertion in this suite is only meaningful if the
    stub is really installed. When VRT-10 moved the routers out of src/main.py,
    the fixture's patch target silently stopped being the object the routers
    use, and every one of those tests kept passing -- because there genuinely is
    no server listening in CI either. A suite that passes for the wrong reason
    is worse than one that fails.

    This asserts the stub recorded the call, so the wiring cannot rot again
    without something going red.
    """
    client.post("/api/auth/login", json={"email": "a@example.test", "password": "hunter22"})

    assert workstation.request_stub.calls, (
        "the offline stub was never called - patch target is wrong"
    )
    assert any("/auth/login" in url for _method, url in workstation.request_stub.calls)
