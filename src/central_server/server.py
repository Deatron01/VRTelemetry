# src/central_server/server.py — full updated file

import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Request, Depends
from fastapi.responses import FileResponse
from typing import Optional
import json

from src.license_service.manager import LicenseManager
from src.license_service.db_schema import initialize_license_schema
from src.license_service.auth_manager import AuthManager
from src.central_server.data_manager import CentralDataManager
from src.central_server.data_schema import initialize_data_schema
from src.utils.logger import setup_logging, logger

setup_logging()
initialize_license_schema()
initialize_data_schema()

app = FastAPI(title="VRTelemetry Central Hub Server")

from fastapi.staticfiles import StaticFiles
from pathlib import Path


_admin_ui_dir = Path(__file__).parent / "admin_ui"
if _admin_ui_dir.exists():
    app.mount("/admin-ui", StaticFiles(directory=_admin_ui_dir, html=True), name="admin_ui")

    
license_mgr = LicenseManager()
data_mgr = CentralDataManager()
auth_mgr = AuthManager()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def require_admin(x_session_token: str = Header(...)) -> dict:
    """
    FastAPI dependency — every admin route declares this and gets a 403
    automatically if the caller's session isn't a valid admin session.
    Session token travels as a header here (not a form field) since these
    are the routes an admin dashboard will call repeatedly, not one-off forms.
    """
    session = auth_mgr.validate_session(x_session_token)
    if not session or session["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin_privileges_required")
    return session


def _authorize_activation(activation_id: str, ip_address: str) -> dict:
    result = license_mgr.heartbeat(activation_id, ip_address)
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=f"Unauthorized activation: {result['reason']}")
    return result


# --- Auth routes (unchanged from before) ---

@app.post("/auth/register")
def register(email: str = Form(...), password: str = Form(...),
             org_name: str = Form(...), display_name: str = Form("")):
    # Public registration always creates a 'researcher' — role escalation only
    # happens through /admin/users/set-role, never through self-registration.
    result = auth_mgr.register(email, password, org_name, display_name, role="researcher")
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return result


@app.post("/auth/login")
def login(email: str = Form(...), password: str = Form(...)):
    result = auth_mgr.login(email, password)
    if not result["ok"]:
        raise HTTPException(status_code=401, detail=result["reason"])
    return result


@app.post("/auth/logout")
def logout(session_token: str = Form(...)):
    auth_mgr.logout(session_token)
    return {"ok": True}


@app.get("/auth/session")
def check_session(session_token: str):
    user = auth_mgr.validate_session(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_or_expired_session")
    return user


# --- License routes (existing, used by the desktop app) ---

@app.post("/license/activate")
def activate_license(
    request: Request,
    license_key: str = Form(...),
    hardware_fingerprint: str = Form(...),
    machine_label: str = Form(""),
    os_platform: str = Form(""),
    app_version: str = Form(""),
):
    result = license_mgr.activate(
        license_key=license_key,
        hardware_fingerprint=hardware_fingerprint,
        machine_label=machine_label,
        os_platform=os_platform,
        app_version=app_version,
        ip_address=_client_ip(request),
    )
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=result["reason"])
    return result


@app.post("/license/heartbeat")
def heartbeat(request: Request, activation_id: str = Form(...)):
    result = license_mgr.heartbeat(activation_id, _client_ip(request))
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=result["reason"])
    return result


# --- Data intake (existing) ---

@app.post("/data/upload-session")
async def upload_session(
    request: Request,
    activation_id: str = Form(...),
    license_id: str = Form(...),
    machine_label: str = Form(""),
    session_id: str = Form(...),
    metadata_json: str = Form(...),
    file: UploadFile = File(...),
):
    ip = _client_ip(request)
    _authorize_activation(activation_id, ip)

    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="metadata_json is not valid JSON")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload")

    result = data_mgr.ingest_session(
        license_id=license_id,
        activation_id=activation_id,
        machine_label=machine_label,
        session_id=session_id,
        original_filename=file.filename or f"{session_id}.parquet",
        file_bytes=file_bytes,
        metadata=metadata,
        ip_address=ip,
    )
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["reason"])
    return result


# ============================================================
# --- ADMIN ROUTES — all gated behind require_admin ---
# ============================================================

@app.get("/admin/users")
def admin_list_users(admin=Depends(require_admin)):
    return auth_mgr.list_users()


@app.post("/admin/users/set-role")
def admin_set_role(target_user_id: str = Form(...), role: str = Form(...), admin=Depends(require_admin)):
    ok = auth_mgr.set_role(target_user_id, role)
    if not ok:
        raise HTTPException(status_code=404, detail="user_not_found")
    logger.warning(f"Admin {admin['email']} set role of {target_user_id} to {role}")
    return {"ok": True}


@app.get("/admin/licenses")
def admin_list_licenses(admin=Depends(require_admin)):
    return license_mgr.list_licenses()


@app.post("/admin/license/create")
def admin_create_license(
    email: str = Form(...),
    org_name: str = Form(...),
    plan: str = Form("standard"),
    max_seats: int = Form(1),
    expires_in_days: Optional[int] = Form(365),
    admin=Depends(require_admin),
):
    result = license_mgr.create_license(email, org_name, plan, max_seats, expires_in_days)
    logger.warning(f"Admin {admin['email']} issued license {result['license_key']} to {email}")
    return result


@app.post("/admin/license/revoke")
def admin_revoke_license(license_key: str = Form(...), reason: str = Form(""), admin=Depends(require_admin)):
    ok = license_mgr.revoke_license(license_key, reason)
    if not ok:
        raise HTTPException(status_code=404, detail="License key not found")
    logger.warning(f"Admin {admin['email']} revoked license {license_key}: {reason}")
    return {"ok": True}


@app.post("/admin/machine/revoke")
def admin_revoke_machine(activation_id: str = Form(...), reason: str = Form(""), admin=Depends(require_admin)):
    ok = license_mgr.revoke_machine(activation_id, reason)
    if not ok:
        raise HTTPException(status_code=404, detail="Activation not found")
    logger.warning(f"Admin {admin['email']} revoked machine activation {activation_id}: {reason}")
    return {"ok": True}


@app.get("/admin/sessions")
def admin_list_all_sessions(license_id: Optional[str] = None, admin=Depends(require_admin)):
    return data_mgr.list_sessions(license_id)

@app.post("/admin/license/extend")
def admin_extend_license(license_key: str = Form(...), additional_days: int = Form(...), admin=Depends(require_admin)):
    result = license_mgr.extend_license(license_key, additional_days)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    logger.warning(f"Admin {admin['email']} extended license {license_key} by {additional_days} days")
    return result

@app.get("/admin/sessions/{upload_id}/download")
def admin_download_session(upload_id: str, admin=Depends(require_admin)):
    path = data_mgr.get_file_path(upload_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Session file not found")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")

@app.post("/data/upload-session-log")
async def upload_session_log(
    request: Request,
    activation_id: str = Form(...),
    license_id: str = Form(...),
    session_id: str = Form(...),
    file: UploadFile = File(...),
):
    ip = _client_ip(request)
    _authorize_activation(activation_id, ip)

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty log upload")

    result = data_mgr.ingest_log(
        license_id=license_id, activation_id=activation_id,
        session_id=session_id, file_bytes=file_bytes
    )
    return result


@app.get("/admin/sessions/{session_id}/log")
def admin_download_session_log(session_id: str, license_id: str, admin=Depends(require_admin)):
    path = data_mgr.get_log_path(session_id, license_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Log not found")
    return FileResponse(path, filename=path.name, media_type="text/plain")