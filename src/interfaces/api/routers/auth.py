# src/interfaces/api/routers/auth.py
"""Account authentication, proxied to the central hub.

Moved from src/main.py. Behaviour is unchanged; the characterisation suite in
tests/characterisation/ is the proof.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.interfaces.api import dependencies as deps
from src.interfaces.api.schemas.auth import AuthLoginRequest, AuthRegisterRequest

router = APIRouter(tags=["auth"])


@router.post("/api/auth/register")
def api_register(payload: AuthRegisterRequest):
    try:
        r = deps.http_requests.post(
            f"{deps.central_url()}/auth/register", data=payload.dict(), timeout=10
        )
    except deps.http_requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}")
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code, detail=r.json().get("detail", "registration_failed")
        )
    return r.json()


@router.post("/api/auth/login")
def api_login(payload: AuthLoginRequest):
    try:
        r = deps.http_requests.post(
            f"{deps.central_url()}/auth/login", data=payload.dict(), timeout=10
        )
    except deps.http_requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach central server: {e}")
    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code, detail=r.json().get("detail", "login_failed")
        )

    data = r.json()
    deps.local_cache.save_session(
        data["session_token"], data["user_id"], data["email"], data.get("display_name", "")
    )
    return data


@router.post("/api/auth/logout")
def api_logout():
    session = deps.local_cache.get_session()
    if session and session.get("session_token"):
        try:
            deps.http_requests.post(
                f"{deps.central_url()}/auth/logout",
                data={"session_token": session["session_token"]},
                timeout=5,
            )
        except deps.http_requests.RequestException:
            pass  # best-effort — clear local state regardless
    deps.local_cache.clear_session()
    return {"ok": True}


@router.get("/api/auth/session")
def api_session():
    """
    Called on app boot to decide whether to show the login screen or the app shell.
    Validates against the central server when reachable; falls back to trusting
    the local cache if the server is unreachable, so a LAN blip mid-recording
    doesn't boot the researcher out mid-session.
    """
    session = deps.local_cache.get_session()
    if not session or not session.get("session_token"):
        return {"authenticated": False}

    try:
        r = deps.http_requests.get(
            f"{deps.central_url()}/auth/session",
            params={"session_token": session["session_token"]},
            timeout=5,
        )
        if r.status_code == 200:
            return {"authenticated": True, **r.json()}
        else:
            deps.local_cache.clear_session()
            return {"authenticated": False}
    except deps.http_requests.RequestException:
        # Central server unreachable — trust the local cache rather than lock the researcher out
        return {
            "authenticated": True,
            "email": session["email"],
            "display_name": session["display_name"],
            "offline": True,
        }
