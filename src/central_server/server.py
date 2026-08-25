# src/central_server/server.py

import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Request
from fastapi.responses import FileResponse
from typing import Optional
import json

from src.license_service.manager import LicenseManager
from src.license_service.db_schema import initialize_license_schema
from src.central_server.data_manager import CentralDataManager
from src.central_server.data_schema import initialize_data_schema
from src.utils.logger import setup_logging, logger

setup_logging()
initialize_license_schema()
initialize_data_schema()

app = FastAPI(title="VRTelemetry Central Hub Server")

license_mgr = LicenseManager()
data_mgr = CentralDataManager()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _authorize_activation(activation_id: str, ip_address: str) -> dict:
    """
    Shared gate for any endpoint that requires a live, non-revoked seat.
    Reuses the same heartbeat validation logic — an upload IS effectively
    a heartbeat, so this keeps 'is this machine still allowed to talk to us'
    consistent across every kind of traffic from the desktop app.
    """
    result = license_mgr.heartbeat(activation_id, ip_address)
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=f"Unauthorized activation: {result['reason']}")
    return result


# --- License routes ---

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


# --- Data intake routes ---

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
    """
    Called by the researcher's local backend once a recording session is
    complete. Requires a live activation — a revoked researcher cannot
    push new data even if their local app is still technically running.
    """
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


# --- Admin routes (you, reviewing collected data) ---

@app.get("/admin/sessions")
def list_all_sessions(license_id: Optional[str] = None):
    return data_mgr.list_sessions(license_id)


@app.get("/admin/sessions/{upload_id}/download")
def download_session(upload_id: str):
    path = data_mgr.get_file_path(upload_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Session file not found")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.post("/admin/license/create")
def admin_create_license(
    email: str = Form(...),
    org_name: str = Form(...),
    plan: str = Form("standard"),
    max_seats: int = Form(1),
    expires_in_days: Optional[int] = Form(365),
):
    return license_mgr.create_license(email, org_name, plan, max_seats, expires_in_days)


@app.post("/admin/license/revoke")
def admin_revoke_license(license_key: str = Form(...), reason: str = Form("")):
    ok = license_mgr.revoke_license(license_key, reason)
    if not ok:
        raise HTTPException(status_code=404, detail="License key not found")
    return {"ok": True}


@app.post("/admin/machine/revoke")
def admin_revoke_machine(activation_id: str = Form(...), reason: str = Form("")):
    ok = license_mgr.revoke_machine(activation_id, reason)
    if not ok:
        raise HTTPException(status_code=404, detail="Activation not found")
    return {"ok": True}