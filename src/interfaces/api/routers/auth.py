# src/interfaces/api/routers/auth.py
"""Account authentication, proxied to the central hub.

Moved from src/main.py in VRT-10; its collaborators became injected parameters
in VRT-12. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, HTTPException

from src.interfaces.api.dependencies import CentralUrlDep, HttpDep, LocalCacheDep
from src.interfaces.api.schemas.auth import AuthLoginRequest, AuthRegisterRequest

router = APIRouter(tags=["auth"])


@router.post("/api/auth/register")
def api_register(payload: AuthRegisterRequest, http: HttpDep, central_url: CentralUrlDep):
    try:
        r = http.post(f"{central_url}/auth/register", data=payload.dict(), timeout=10)
    except http.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}") from e
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code, detail=r.json().get("detail", "registration_failed")
        )
    return r.json()


@router.post("/api/auth/login")
def api_login(
    payload: AuthLoginRequest,
    http: HttpDep,
    central_url: CentralUrlDep,
    local_cache: LocalCacheDep,
):
    try:
        r = http.post(f"{central_url}/auth/login", data=payload.dict(), timeout=10)
    except http.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}") from e
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code, detail=r.json().get("detail", "login_failed")
        )

    data = r.json()
    local_cache.save_session(
        data["session_token"], data["user_id"], data["email"], data.get("display_name", "")
    )
    return data


@router.post("/api/auth/logout")
def api_logout(http: HttpDep, central_url: CentralUrlDep, local_cache: LocalCacheDep):
    session = local_cache.get_session()
    if session and session.get("session_token"):
        # Telling the hub is courtesy; clearing the local session is the actual
        # logout, and it happens below whatever the hub says. Suppressed rather
        # than logged because "the hub was unreachable while logging out" is the
        # expected state on a laptop, not an event.
        with contextlib.suppress(http.RequestException):
            http.post(
                f"{central_url}/auth/logout",
                data={"session_token": session["session_token"]},
                timeout=5,
            )
    local_cache.clear_session()
    return {"ok": True}


@router.get("/api/auth/session")
def api_session(http: HttpDep, central_url: CentralUrlDep, local_cache: LocalCacheDep):
    """
    Called on app boot to decide whether to show the login screen or the app shell.
    Validates against the central server when reachable; falls back to trusting
    the local cache if the server is unreachable, so a LAN blip mid-recording
    doesn't boot the researcher out mid-session.
    """
    session = local_cache.get_session()
    if not session or not session.get("session_token"):
        return {"authenticated": False}

    try:
        r = http.get(
            f"{central_url}/auth/session",
            params={"session_token": session["session_token"]},
            timeout=5,
        )
        if r.status_code == 200:
            return {"authenticated": True, **r.json()}
        else:
            local_cache.clear_session()
            return {"authenticated": False}
    except http.RequestException:
        # Central server unreachable — trust the local cache rather than lock the researcher out
        return {
            "authenticated": True,
            "email": session["email"],
            "display_name": session["display_name"],
            "offline": True,
        }
