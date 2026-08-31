# src/central_server/server.py — full updated file
import os
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


def _authorize_activation(activation_id: str, ip_address: str, machine_label: Optional[str] = None) -> dict:
    result = license_mgr.heartbeat(activation_id, ip_address, machine_label=machine_label)
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=f"Unauthorized activation: {result['reason']}")
    return result


# Heartbeats older than this are considered offline in the Active Clients view.
# 3x the client's 30s ping interval gives headroom for one or two missed beats
# (a brief network blip) before flipping a machine to "Offline".
CLIENT_ONLINE_THRESHOLD_SECONDS = 90


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
def heartbeat(request: Request, activation_id: str = Form(...), machine_label: Optional[str] = Form(None)):
    result = license_mgr.heartbeat(activation_id, _client_ip(request), machine_label=machine_label)
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=result["reason"])
    return result


@app.post("/client/heartbeat")
def client_heartbeat(
    request: Request,
    activation_id: str = Form(...),
    license_id: str = Form(""),
    machine_label: str = Form(""),
    app_version: str = Form(""),
    os_platform: str = Form(""),
    status: str = Form("idle"),
    pending_sync_count: int = Form(0),
):
    """
    Dedicated presence/liveness ping — separate from /license/heartbeat so the
    Active Clients admin view has richer, purpose-built data (app_version,
    os_platform, current status, how much is still queued locally) without
    overloading the license-validity endpoint. Still goes through the same
    activation authorization, so a revoked/expired machine can't keep showing
    up as "online".
    """
    ip = _client_ip(request)
    auth = _authorize_activation(activation_id, ip, machine_label=machine_label or None)
    data_mgr.record_heartbeat(
        activation_id=activation_id,
        license_id=license_id or auth.get("license_id") or "",
        machine_label=machine_label,
        app_version=app_version,
        os_platform=os_platform,
        status=status,
        pending_sync_count=pending_sync_count,
        ip_address=ip,
    )
    return {"ok": True, "expires_at": auth.get("expires_at")}


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


@app.post("/data/update-session-metadata")
async def update_session_metadata(
    request: Request,
    activation_id: str = Form(...),
    license_id: str = Form(...),
    session_id: str = Form(...),
    metadata_json: str = Form(...),
):
    """
    Metadata-only update for a session that already uploaded its Parquet file —
    used when a post-session questionnaire (SSQ/NASA-TLX/thermal comfort) is
    completed after the fact. See CentralDataManager.update_session_metadata
    for why this can't just reuse /data/upload-session.
    """
    ip = _client_ip(request)
    _authorize_activation(activation_id, ip)

    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="metadata_json is not valid JSON")

    result = data_mgr.update_session_metadata(license_id=license_id, session_id=session_id, metadata=metadata)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
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


@app.get("/admin/clients")
def admin_list_clients(admin=Depends(require_admin)):
    """
    Merges every machine ever activated (LicenseManager, licenses.db) with the
    live presence data reported via /client/heartbeat (CentralDataManager,
    central_data.db). A machine shows up here even if it has never sent an
    app-level heartbeat yet (e.g. an older client build) — it just falls back
    to the license heartbeat's last_heartbeat_at and reads as Offline/Unknown
    once that ages past the threshold.
    """
    import datetime as _dt

    activations = {a["activation_id"]: a for a in license_mgr.list_activations()}
    heartbeats = {h["activation_id"]: h for h in data_mgr.list_client_heartbeats()}

    now = _dt.datetime.utcnow()
    clients = []
    for aid in set(activations) | set(heartbeats):
        act = activations.get(aid, {})
        hb = heartbeats.get(aid, {})
        last_seen = hb.get("last_seen_at") or act.get("last_heartbeat_at")

        seconds_since_seen = None
        online = False
        if last_seen:
            try:
                last_dt = _dt.datetime.fromisoformat(str(last_seen))
                seconds_since_seen = (now - last_dt).total_seconds()
                online = 0 <= seconds_since_seen <= CLIENT_ONLINE_THRESHOLD_SECONDS
            except ValueError:
                pass

        clients.append({
            "activation_id": aid,
            "machine_label": hb.get("machine_label") or act.get("machine_label"),
            "hardware_fingerprint": act.get("hardware_fingerprint"),
            "license_key": act.get("license_key"),
            "license_id": act.get("license_id") or hb.get("license_id"),
            "license_status": act.get("license_status"),
            "plan": act.get("plan"),
            "org_name": act.get("org_name"),
            "owner_email": act.get("owner_email"),
            "os_platform": hb.get("os_platform") or act.get("os_platform"),
            "app_version": hb.get("app_version") or act.get("app_version"),
            "status": hb.get("status") or ("unknown" if act else "unknown"),
            "pending_sync_count": hb.get("pending_sync_count", 0),
            "ip_address": hb.get("ip_address"),
            "is_revoked": bool(act.get("is_revoked", 0)),
            "activated_at": act.get("activated_at"),
            "first_seen_at": hb.get("first_seen_at"),
            "last_seen_at": last_seen,
            "seconds_since_seen": seconds_since_seen,
            "online": online,
        })

    clients.sort(key=lambda c: c["last_seen_at"] or "", reverse=True)
    return clients

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

@app.post("/data/upload-patient")
async def upload_patient(request: Request, payload: dict):
    ip = _client_ip(request)
    activation_id = payload.get("activation_id")
    license_id = payload.get("license_id")
    patient = payload.get("patient")
    
    # Check for None explicitly rather than truthiness, to allow empty strings if necessary
    if activation_id is None or license_id is None or patient is None or not patient.get("patient_id"):
        # Optional: Print to backend console to see exactly what is missing
        logger.error(f"Sync rejected. Payload received: {payload}") 
        raise HTTPException(status_code=400, detail="activation_id, license_id, and patient are required")

    _authorize_activation(activation_id, ip)
    return data_mgr.upsert_patient(license_id=license_id, activation_id=activation_id, patient=patient)


@app.get("/admin/patients")
def admin_list_patients(license_id: Optional[str] = None, admin=Depends(require_admin)):
    return data_mgr.list_patients(license_id)

@app.get("/admin/sessions/{session_id}/log")
def admin_download_session_log(session_id: str, license_id: str, admin=Depends(require_admin)):
    path = data_mgr.get_log_path(session_id, license_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Log not found")
    return FileResponse(path, filename=path.name, media_type="text/plain")

# ============================================================
# --- DATABASE FILES ROUTES ---
# ============================================================

def _get_storage_root() -> Path:
    # Safely extract the root path from data_mgr. 
    # Change 'storage_dir' to match whatever attribute CentralDataManager uses.
    root = getattr(data_mgr, 'storage_dir', None) or getattr(data_mgr, 'base_dir', Path("data"))
    return Path(root)

@app.get("/admin/files")
def admin_list_files(admin=Depends(require_admin)):
    files = []
    storage_root = _get_storage_root()
    
    if storage_root.exists():
        for file_path in storage_root.rglob("*"):
            if file_path.is_file():
                stat = file_path.stat()
                # Use the relative path as the ID so it's clean in the frontend
                rel_path = file_path.relative_to(storage_root)
                rel_str = str(rel_path).replace("\\", "/")
                parts = rel_str.split("/")
                files.append({
                    "id": rel_str,
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "type": file_path.suffix.lstrip('.') or "unknown",
                    "last_modified": stat.st_mtime * 1000,
                    # Files are stored namespaced by license (CentralDataManager.ingest_session /
                    # ingest_log) — surfacing that top-level segment lets the admin UI filter/group
                    # raw files by license without a second lookup.
                    "license_id": parts[0] if len(parts) > 1 else None,
                    "relative_dir": "/".join(parts[:-1]) if len(parts) > 1 else "",
                })
    return files

@app.get("/admin/files/{file_id:path}/download")
def admin_download_raw_file(file_id: str, admin=Depends(require_admin)):
    storage_root = _get_storage_root()
    path = (storage_root / file_id).resolve()
    
    # Security check: prevent directory traversal attacks (e.g., ../../../etc/passwd)
    if not path.exists() or not path.is_file() or storage_root.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="File not found or access denied")
    
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")

@app.delete("/admin/files/{file_id:path}")
def admin_delete_raw_file(file_id: str, admin=Depends(require_admin)):
    storage_root = _get_storage_root()
    path = (storage_root / file_id).resolve()
    
    if not path.exists() or not path.is_file() or storage_root.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="File not found or access denied")
    
    try:
        path.unlink()
        logger.warning(f"Admin {admin['email']} deleted raw file: {file_id}")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")