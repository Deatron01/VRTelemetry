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
}


# --------------------------------------------------------------------------- #
# Recording lifecycle -- the refusals
# --------------------------------------------------------------------------- #


def test_recording_start_requires_a_recorded_participant_consent(
    client: TestClient, workstation: Any
) -> None:
    """Inverted in GDPR-09, deliberately.

    This used to assert that the *request's* ``gdpr_consent`` boolean -- a box
    the researcher ticked -- was required. That box is gone. A patient row
    whose consent flag is set but who has no consent in the register (the only
    kind of patient that could exist before GDPR-09) cannot be recorded, and
    ``"gdpr_consent": true`` on the request changes nothing.
    """
    legacy = workstation.patients.create_patient(display_name="Legacy", gdpr_consent_given=True)

    response = client.post(
        "/api/recording/start",
        json={**START_BODY, "patient_id": legacy["patient_id"], "gdpr_consent": True},
    )

    assert response.status_code == 403
    assert "no valid consent" in response.json()["detail"]


def test_recording_start_refuses_a_consent_that_belongs_to_someone_else(
    client: TestClient, workstation: Any, patient: dict[str, Any]
) -> None:
    other = workstation.patients.create_patient(display_name="Other", gdpr_consent_given=True)

    response = client.post(
        "/api/recording/start",
        json={**START_BODY, "patient_id": other["patient_id"], "consent_id": patient["consent_id"]},
    )

    assert response.status_code == 403
    assert "does not belong" in response.json()["detail"]


def test_recording_start_requires_a_known_patient(client: TestClient) -> None:
    response = client.post("/api/recording/start", json={**START_BODY, "patient_id": "nope"})

    assert response.status_code == 404


def test_recording_start_is_refused_after_consent_withdrawal(
    client: TestClient, workstation: Any, patient: dict[str, Any]
) -> None:
    """A withdrawn consent stops recording, whatever the request says."""
    workstation.patients.withdraw_consent(patient["patient_id"])

    response = client.post(
        "/api/recording/start", json={**START_BODY, "patient_id": patient["patient_id"]}
    )

    assert response.status_code == 403
    assert "consent is not active" in response.json()["detail"]


def test_recording_start_is_refused_for_an_erased_patient(
    client: TestClient, workstation: Any, patient: dict[str, Any]
) -> None:
    workstation.patients.delete_patient(patient["patient_id"], hard_delete=False)

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
    workstation.local_cache.queue_pending_upload("20260527_133428", "s.parquet", "{}")

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
    workstation.local_cache.save_session("tok-123", "user-1", "a@example.test", "Researcher A")

    body = client.get("/api/auth/session").json()

    assert body["authenticated"] is True
    assert body["offline"] is True
    assert body["email"] == "a@example.test"


def test_auth_logout_clears_local_state_even_when_the_server_is_unreachable(
    client: TestClient, workstation: Any
) -> None:
    """Logging out must always work locally. A user asking to be logged out is
    not making a request that a network failure may decline."""
    workstation.local_cache.save_session("tok-123", "user-1", "a@example.test", "Researcher A")

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
    """Setting one works as before; only the unset case changed.

    An ``https://`` address since GDPR-01: plain HTTP to a LAN host is refused
    at save time, see tests/integration/test_hub_connection.py.
    """
    client.post("/api/config/central-server", json={"central_server_url": "https://10.0.0.9:9000"})

    assert client.get("/api/config/central-server").json() == {
        "central_server_url": "https://10.0.0.9:9000"
    }


def test_central_server_url_round_trips_through_the_local_cache(client: TestClient) -> None:
    new_url = "https://192.168.1.50:9000"

    assert client.post(
        "/api/config/central-server", json={"central_server_url": new_url}
    ).json() == {
        "ok": True,
        "central_server_url": new_url,
    }
    assert client.get("/api/config/central-server").json()["central_server_url"] == new_url


def test_changing_the_central_url_repoints_the_live_uploaders(
    client: TestClient, workstation: Any
) -> None:
    """Inverted in VRT-12, deliberately. It used to pin a real wart.

    The uploaders were constructed at import time with the hub address
    evaluated once. Changing it through this route updated the cache and every
    subsequent lookup, but the two long-lived uploaders kept the address they
    were born with until the process restarted -- so a researcher who corrected
    a mistyped server address and did not restart watched uploads keep failing
    against the old one, with nothing anywhere saying why.

    The composition root passes the *resolver* rather than its current value,
    so the address is late-bound everywhere it is used. The previous version of
    this test asserted the opposite and said, in its docstring, that it would
    need inverting when VRT-12 landed. This is that inversion.
    """
    new_url = "https://10.0.0.9:9000"

    client.post("/api/config/central-server", json={"central_server_url": new_url})

    assert workstation.central_url() == new_url
    assert workstation.session_uploader.central_server_url == new_url
    assert workstation.patient_uploader.central_server_url == new_url


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

    assert workstation.http.calls, "the offline stub was never called - patch target is wrong"
    assert any("/auth/login" in url for _method, url in workstation.http.calls)
