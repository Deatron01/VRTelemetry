# src/central_server/server.py — full updated file
import json
import os
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from src.central_server import pairing
from src.central_server.data_manager import CentralDataManager
from src.central_server.data_schema import initialize_data_schema
from src.config import get_settings
from src.infrastructure.persistence.connection import describe_health
from src.infrastructure.transport import is_loopback_host
from src.license_service.auth_manager import AuthManager
from src.license_service.db_schema import initialize_license_schema
from src.license_service.manager import LicenseManager
from src.utils.clock import parse_utc, utc_now
from src.utils.logger import logger, setup_logging
from src.version import APP_VERSION

setup_logging()
initialize_license_schema()
initialize_data_schema()

app = FastAPI(title="VRTelemetry Central Hub Server")

from pathlib import Path

from fastapi.staticfiles import StaticFiles

_admin_ui_dir = Path(__file__).parent / "admin_ui"
if _admin_ui_dir.exists():
    app.mount("/admin-ui", StaticFiles(directory=_admin_ui_dir, html=True), name="admin_ui")


license_mgr = LicenseManager()
data_mgr = CentralDataManager()
auth_mgr = AuthManager()


@app.get("/health", tags=["health"])
def health() -> dict[str, Any]:
    """Whether this hub is running, and whether its database answers.

    Unauthenticated and deliberately cheap. It exists for two callers with the
    same question asked at different moments:

    * a researcher setting up a workstation, who needs to know whether the
      address they typed reaches a hub at all -- before discovering otherwise at
      the end of a recording, which is when they used to find out;
    * ``POST /api/config/central-server/check`` on the workstation, which asks
      this on their behalf and reports the answer in the app.

    Always returns 200, including when the database is broken. The distinction
    that matters to the caller is "did anything answer" versus "nothing
    answered", and a 503 collapses the second case into the first: an
    unreachable host and an unhealthy one would both surface as a failed
    request. ``ok`` carries the health; the status code carries reachability.

    Returns:
        ``service`` and ``version`` so a workstation pointed at the wrong
        service on the right port can tell; ``database`` is ``"ok"`` or the
        error, so "the hub is up but cannot store anything" is visible rather
        than being discovered on the first upload.
    """
    database = describe_health(get_settings().paths.central_data_db)
    if database != "ok":
        logger.error(f"Health check: central database is not answering: {database}")

    return {
        "ok": database == "ok",
        "service": "vrtelemetry-hub",
        "version": APP_VERSION,
        "database": database,
    }


@app.get("/api/plugins/catalog", tags=["plugins"])
def plugin_catalog() -> list[dict[str, Any]]:
    """The list of Core Hub plugins this deployment's operator has approved.

    Unauthenticated, like `/health`: unlike every data-intake route above,
    this carries no participant data and no tenant scoping -- it is the same
    list for every workstation that asks, the way a package registry's index
    is the same for every client. A workstation's own
    `GET /api/plugins/catalog` (`src.interfaces.api.routers.plugins`) fetches
    this and re-serves it to its own researcher-facing UI.

    Backed by the `plugin_catalog` table (`CentralDataManager.list_plugins`)
    rather than `plugin_catalog.json` directly -- that file is now only the
    one-time seed `data_schema.seed_plugin_catalog_from_json` migrates into
    the table on first boot; edit the catalog through the admin dashboard's
    Plugin Catalog tab (`/admin/plugins/*`) from here on. `published_only`
    excludes anything an admin has added but not yet published -- see
    `data_schema.py`'s `plugin_catalog` table comment for why those are two
    different actions.

    Returns:
        Each entry's `plugin_id`, `name`, `description`, `repo_url`, `ref`,
        `homepage` and `maintainer` -- see
        `src.central_server.plugin_catalog.CatalogEntry`.
    """
    return data_mgr.list_plugins(published_only=True)


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


def _authorize_activation(
    activation_id: str, ip_address: str, machine_label: str | None = None
) -> dict:
    """Authorise a machine activation and return its authoritative licence context.

    The returned dict carries ``license_id`` resolved by joining
    ``machine_activations`` to ``licenses`` server-side. Callers must use *that*
    value to scope any write. See :func:`_authorize_write`.

    Args:
        activation_id: The activation the client claims to be.
        ip_address: Caller IP, recorded in the licence event log.
        machine_label: Updates the stored label when supplied; ``None`` leaves it.

    Returns:
        The heartbeat result, including ``license_id`` and ``expires_at``.

    Raises:
        HTTPException: 403 if the activation is unknown, revoked or expired.
    """
    result = license_mgr.heartbeat(activation_id, ip_address, machine_label=machine_label)
    if not result["ok"]:
        raise HTTPException(status_code=403, detail=f"Unauthorized activation: {result['reason']}")
    return result


def _authorize_write(
    activation_id: str,
    ip_address: str,
    claimed_license_id: str | None = None,
    machine_label: str | None = None,
) -> dict:
    """Authorise a tenant write, ignoring the licence the client claims.

    Every data-intake route previously authorised the ``activation_id`` and then
    passed the client's own ``license_id`` straight through to CentralDataManager
    unverified. Any holder of a valid activation could therefore file sessions,
    session logs and patient records under another organisation's licence -- an
    IDOR across a tenancy boundary, on a server holding special-category health
    data.

    The fix is to derive the tenant from the authorised activation. The client's
    value is not trusted, but it is still *compared* for one release rather than
    silently ignored: an older or tampered client fails loudly with a 403 and an
    audit line, instead of quietly having its uploads refiled somewhere it did
    not expect. Once no deployed client sends the field, drop the parameter.

    Args:
        activation_id: The activation the client claims to be.
        ip_address: Caller IP, for the licence event log and the audit line.
        claimed_license_id: The client-supplied value, compared but never used.
        machine_label: Passed through to the heartbeat.

    Returns:
        The heartbeat result. Its ``license_id`` is the authoritative tenant for
        this activation and is what callers must scope their write to;
        ``expires_at`` is carried along so routes that report it back to the
        client do not have to issue a second heartbeat to obtain it.

    Raises:
        HTTPException: 403 if the activation is unauthorised, or if the claimed
            licence does not match the one the activation actually belongs to.
    """
    auth = _authorize_activation(activation_id, ip_address, machine_label=machine_label)
    license_id: str = auth["license_id"]

    if claimed_license_id and claimed_license_id != license_id:
        # Log identifiers only -- no payload. See VRT-3.
        logger.error(
            "Cross-tenant write rejected: activation=%s ip=%s claimed_license=%s",
            activation_id,
            ip_address,
            claimed_license_id,
        )
        raise HTTPException(
            status_code=403,
            detail="license_id does not match the authorised activation",
        )

    return auth


# Heartbeats older than this are considered offline in the Active Clients view.
# 3x the client's 30s ping interval gives headroom for one or two missed beats
# (a brief network blip) before flipping a machine to "Offline".
CLIENT_ONLINE_THRESHOLD_SECONDS = 90


# --- Auth routes (unchanged from before) ---


@app.post("/auth/register")
def register(
    email: str = Form(...),
    password: str = Form(...),
    org_name: str = Form(...),
    display_name: str = Form(""),
):
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
def heartbeat(
    request: Request, activation_id: str = Form(...), machine_label: str | None = Form(None)
):
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
    # This writes a presence row scoped to a licence, so it is a tenant write
    # like any other: it preferred the client's own license_id over the
    # authorised one, which let a machine appear in another organisation's
    # Active Clients view.
    auth = _authorize_write(
        activation_id, ip, license_id or None, machine_label=machine_label or None
    )
    data_mgr.record_heartbeat(
        activation_id=activation_id,
        license_id=auth["license_id"],
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
    auth = _authorize_write(activation_id, ip, license_id, machine_label=machine_label)

    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="metadata_json is not valid JSON") from e

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload")

    result = data_mgr.ingest_session(
        license_id=auth["license_id"],
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
    auth = _authorize_write(activation_id, ip, license_id)

    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="metadata_json is not valid JSON") from e

    result = data_mgr.update_session_metadata(
        license_id=auth["license_id"], session_id=session_id, metadata=metadata
    )
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
def admin_set_role(
    target_user_id: str = Form(...), role: str = Form(...), admin=Depends(require_admin)
):
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
    expires_in_days: int | None = Form(365),
    admin=Depends(require_admin),
):
    result = license_mgr.create_license(email, org_name, plan, max_seats, expires_in_days)
    logger.warning(f"Admin {admin['email']} issued license {result['license_key']} to {email}")
    return result


@app.post("/admin/license/revoke")
def admin_revoke_license(
    license_key: str = Form(...), reason: str = Form(""), admin=Depends(require_admin)
):
    ok = license_mgr.revoke_license(license_key, reason)
    if not ok:
        raise HTTPException(status_code=404, detail="License key not found")
    logger.warning(f"Admin {admin['email']} revoked license {license_key}: {reason}")
    return {"ok": True}


@app.post("/admin/machine/revoke")
def admin_revoke_machine(
    activation_id: str = Form(...), reason: str = Form(""), admin=Depends(require_admin)
):
    ok = license_mgr.revoke_machine(activation_id, reason)
    if not ok:
        raise HTTPException(status_code=404, detail="Activation not found")
    logger.warning(f"Admin {admin['email']} revoked machine activation {activation_id}: {reason}")
    return {"ok": True}


@app.get("/admin/sessions")
def admin_list_all_sessions(license_id: str | None = None, admin=Depends(require_admin)):
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
    activations = {a["activation_id"]: a for a in license_mgr.list_activations()}
    heartbeats = {h["activation_id"]: h for h in data_mgr.list_client_heartbeats()}

    now = utc_now()
    clients = []
    for aid in set(activations) | set(heartbeats):
        act = activations.get(aid, {})
        hb = heartbeats.get(aid, {})
        last_seen = hb.get("last_seen_at") or act.get("last_heartbeat_at")

        seconds_since_seen = None
        online = False
        last_dt = parse_utc(last_seen)
        if last_dt is not None:
            seconds_since_seen = (now - last_dt).total_seconds()
            online = 0 <= seconds_since_seen <= CLIENT_ONLINE_THRESHOLD_SECONDS

        clients.append(
            {
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
            }
        )

    clients.sort(key=lambda c: c["last_seen_at"] or "", reverse=True)
    return clients


@app.post("/admin/license/extend")
def admin_extend_license(
    license_key: str = Form(...), additional_days: int = Form(...), admin=Depends(require_admin)
):
    result = license_mgr.extend_license(license_key, additional_days)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    logger.warning(
        f"Admin {admin['email']} extended license {license_key} by {additional_days} days"
    )
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
    auth = _authorize_write(activation_id, ip, license_id)

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty log upload")

    result = data_mgr.ingest_log(
        license_id=auth["license_id"],
        activation_id=activation_id,
        session_id=session_id,
        file_bytes=file_bytes,
    )
    return result


class PatientUploadRequest(BaseModel):
    """Wire model for a patient record pushed from a researcher workstation.

    Replaces an untyped ``payload: dict``. Two things change as a result:

    1. FastAPI rejects a malformed body with a 422 and a per-field error before
       any application code runs, so the hand-rolled ``is None`` checks -- and
       the log statement that dumped the whole payload when they tripped --
       are no longer needed.
    2. The error response describes which field is wrong without the server
       having to echo the submitted values back into a log file.

    ``patient`` stays a free-form mapping deliberately: its shape is owned by
    ``PatientManager`` on the workstation side and both ends must be able to
    roll forward independently. Pinning it here would turn every new patient
    field into a coordinated deployment. Extracting it into a shared versioned
    contract is VRT-15.
    """

    activation_id: str = Field(min_length=1)
    license_id: str = Field(min_length=1)
    patient: dict[str, Any]

    @field_validator("patient")
    @classmethod
    def _patient_must_be_identifiable(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Reject a patient record with no id -- it cannot be upserted against."""
        if not value.get("patient_id"):
            raise ValueError("patient.patient_id is required")
        return value


@app.post("/data/upload-patient")
async def upload_patient(request: Request, payload: PatientUploadRequest):
    """Upsert a patient record from an authorised workstation.

    The tenant this record is filed under is derived from the authorised
    activation, never from the request body -- see :func:`_authorize_write`.
    """
    ip = _client_ip(request)
    auth = _authorize_write(payload.activation_id, ip, payload.license_id)
    return data_mgr.upsert_patient(
        license_id=auth["license_id"],
        activation_id=payload.activation_id,
        patient=payload.patient,
    )


class PatientErasureRequest(BaseModel):
    """A workstation passing on a participant's erasure request (GDPR-10)."""

    activation_id: str = Field(min_length=1)
    license_id: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    session_ids: list[str] = Field(default_factory=list)


@app.post("/data/erase-patient")
async def erase_patient(request: Request, payload: PatientErasureRequest):
    """Delete everything the hub holds for one patient.

    Scoped to the tenant derived from the authorised activation, exactly like
    every other write -- see :func:`_authorize_write`. Answers 409 when some
    file could not be deleted, so the workstation keeps the request queued and
    tries again rather than believing the erasure is done.
    """
    ip = _client_ip(request)
    auth = _authorize_write(payload.activation_id, ip, payload.license_id)
    result = data_mgr.erase_patient(
        license_id=auth["license_id"],
        activation_id=payload.activation_id,
        patient_id=payload.patient_id,
        session_ids=payload.session_ids,
        ip_address=ip,
    )
    if not result["complete"]:
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/admin/patients")
def admin_list_patients(license_id: str | None = None, admin=Depends(require_admin)):
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
    root = getattr(data_mgr, "storage_dir", None) or getattr(data_mgr, "base_dir", Path("data"))
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
                files.append(
                    {
                        "id": rel_str,
                        "filename": file_path.name,
                        "size": stat.st_size,
                        "type": file_path.suffix.lstrip(".") or "unknown",
                        "last_modified": stat.st_mtime * 1000,
                        # Files are stored namespaced by license (CentralDataManager.ingest_session /
                        # ingest_log) — surfacing that top-level segment lets the admin UI filter/group
                        # raw files by license without a second lookup.
                        "license_id": parts[0] if len(parts) > 1 else None,
                        "relative_dir": "/".join(parts[:-1]) if len(parts) > 1 else "",
                    }
                )
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
    except OSError as e:
        # The file exists (checked above) but could not be removed: permissions,
        # or another process holding it open, which on Windows is the ordinary
        # case rather than the exotic one. Narrowed from `Exception` so that a
        # defect in the path handling above surfaces as a real 500 with a
        # traceback instead of being reported to an admin as a locked file.
        logger.error(f"Admin {admin['email']} could not delete raw file {file_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e!s}") from e

    logger.warning(f"Admin {admin['email']} deleted raw file: {file_id}")
    return {"ok": True}


# ============================================================
# --- PLUGIN CATALOG ROUTES (admin dashboard's Plugin Catalog tab) ---
# ============================================================


@app.get("/admin/plugins")
def admin_list_plugins(admin=Depends(require_admin)) -> list[dict[str, Any]]:
    """Every catalog entry, published or not -- unlike the public
    `GET /api/plugins/catalog`, which only ever returns published ones."""
    return data_mgr.list_plugins()


@app.post("/admin/plugins/create")
def admin_create_plugin(
    plugin_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    repo_url: str = Form(...),
    ref: str = Form("main"),
    homepage: str = Form(""),
    maintainer: str = Form(""),
    admin=Depends(require_admin),
) -> dict[str, Any]:
    """Add a catalog entry. Unpublished until an admin explicitly publishes
    it -- see `data_schema.py`'s `plugin_catalog` table comment."""
    ok = data_mgr.add_plugin(
        plugin_id=plugin_id,
        name=name,
        description=description,
        repo_url=repo_url,
        ref=ref or "main",
        homepage=homepage or None,
        maintainer=maintainer or None,
    )
    if not ok:
        raise HTTPException(status_code=409, detail=f"'{plugin_id}' is already in the catalog.")
    logger.warning(
        f"Admin {admin['email']} added plugin '{plugin_id}' to the catalog (unpublished)."
    )
    return {"ok": True}


@app.post("/admin/plugins/update")
def admin_update_plugin(
    plugin_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    repo_url: str = Form(...),
    ref: str = Form("main"),
    homepage: str = Form(""),
    maintainer: str = Form(""),
    admin=Depends(require_admin),
) -> dict[str, Any]:
    ok = data_mgr.update_plugin(
        plugin_id,
        name=name,
        description=description,
        repo_url=repo_url,
        ref=ref or "main",
        homepage=homepage or None,
        maintainer=maintainer or None,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"'{plugin_id}' is not in the catalog.")
    logger.warning(f"Admin {admin['email']} edited plugin '{plugin_id}'.")
    return {"ok": True}


@app.post("/admin/plugins/publish")
def admin_publish_plugin(
    plugin_id: str = Form(...), admin=Depends(require_admin)
) -> dict[str, Any]:
    """Make a catalog entry visible on `GET /api/plugins/catalog` -- the
    moment a workstation can actually see and install it."""
    ok = data_mgr.set_plugin_published(plugin_id, True)
    if not ok:
        raise HTTPException(status_code=404, detail=f"'{plugin_id}' is not in the catalog.")
    logger.warning(f"Admin {admin['email']} published plugin '{plugin_id}' to the catalog.")
    return {"ok": True}


@app.post("/admin/plugins/unpublish")
def admin_unpublish_plugin(
    plugin_id: str = Form(...), admin=Depends(require_admin)
) -> dict[str, Any]:
    """Hide a catalog entry from `GET /api/plugins/catalog` without deleting
    it -- e.g. a plugin under review again, or a repo that's temporarily
    broken. Anyone who already installed it keeps running; this only
    controls what new installs can see."""
    ok = data_mgr.set_plugin_published(plugin_id, False)
    if not ok:
        raise HTTPException(status_code=404, detail=f"'{plugin_id}' is not in the catalog.")
    logger.warning(f"Admin {admin['email']} unpublished plugin '{plugin_id}' from the catalog.")
    return {"ok": True}


@app.delete("/admin/plugins/{plugin_id}")
def admin_delete_plugin(plugin_id: str, admin=Depends(require_admin)) -> dict[str, Any]:
    ok = data_mgr.delete_plugin(plugin_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"'{plugin_id}' is not in the catalog.")
    logger.warning(f"Admin {admin['email']} deleted plugin '{plugin_id}' from the catalog.")
    return {"ok": True}


# ============================================================
# --- WORKSTATION PAIRING (admin UI's "Pair a Workstation" tab) ---
# ============================================================


def hub_ca_path() -> Path:
    """The CA certificate workstations are paired with.

    ``hub-ca.pem`` beside the configured certificate -- where ``gen-cert`` and
    ``setup`` put it -- or, with no certificate configured, the default
    ``CentralServer/tls`` directory those tools write to.
    """
    settings = get_settings()
    if settings.hub.tls_certfile:
        return Path(settings.hub.tls_certfile).parent / "hub-ca.pem"
    return settings.paths.central_dir / "tls" / "hub-ca.pem"


pairing_service = pairing.PairingService(lambda: hub_ca_path().read_text(encoding="ascii"))
app.include_router(pairing.build_router(pairing_service, require_admin))


def resolve_bind_address() -> tuple[str, int]:
    """Where this hub should listen, and why.

    Separate from :func:`main` so it can be tested without starting a server --
    which is the whole difficulty with binding bugs: the only way to observe one
    used to be to run the thing and see where it turned up.

    Returns:
        Host and port, from :class:`~src.config.settings.HubSettings`, with the
        pre-VRT-6 ``VRT_HUB_HOST`` / ``VRT_HUB_PORT`` spelling honoured on top
        if it is present. Honoured rather than ignored: a deployment or a
        desktop shortcut may still set it, and silently binding somewhere other
        than where you were told is the exact failure this function exists to
        end.
    """
    settings = get_settings().hub
    host, port = settings.host, settings.port

    for old, new in (("VRT_HUB_HOST", "VRT_HUB__HOST"), ("VRT_HUB_PORT", "VRT_HUB__PORT")):
        value = os.environ.get(old)
        if value is None:
            continue
        logger.warning(
            f"{old} is the pre-VRT-6 spelling and is deprecated; use {new} "
            f"(double underscore) or a [hub] block in config.toml. Honouring it."
        )
        if old.endswith("HOST"):
            host = value
        else:
            port = int(value)

    return host, port


class HubTlsNotConfiguredError(RuntimeError):
    """The hub was asked to listen on the network without TLS (GDPR-01)."""


def resolve_tls(host: str) -> dict[str, str]:
    """The uvicorn TLS arguments for this hub, or a refusal to start without them.

    The hub receives participant records and eye-tracking telemetry from every
    workstation on the LAN. Served over plain HTTP, all of it crosses the
    network in clear text, which Art. 32 GDPR does not allow for data of this
    sensitivity. So:

    * certificate and key configured -- serve HTTPS;
    * bound to loopback only -- plain HTTP is allowed (a one-machine
      development setup: the traffic never leaves the host);
    * ``hub.allow_insecure_http`` set -- plain HTTP, with a warning on start;
    * otherwise -- refuse, naming the fix.

    Args:
        host: The interface the hub will bind, from :func:`resolve_bind_address`.

    Returns:
        ``{"ssl_certfile": ..., "ssl_keyfile": ...}`` or ``{}`` for plain HTTP.

    Raises:
        HubTlsNotConfiguredError: on a network interface with no certificate
            and no explicit opt-out, or when a configured file is missing.
    """
    settings = get_settings().hub
    if settings.tls_certfile and settings.tls_keyfile:
        for label, path in (("certificate", settings.tls_certfile), ("key", settings.tls_keyfile)):
            if not Path(path).is_file():
                raise HubTlsNotConfiguredError(f"TLS {label} file not found: {path}")
        return {
            "ssl_certfile": str(settings.tls_certfile),
            "ssl_keyfile": str(settings.tls_keyfile),
        }

    if is_loopback_host(host):
        return {}

    if settings.allow_insecure_http:
        logger.warning(
            "hub.allow_insecure_http is set: this hub accepts participant data over "
            "PLAIN HTTP on the network. Never use this with real participants."
        )
        return {}

    raise HubTlsNotConfiguredError(
        f"Refusing to serve participant data on {host} without TLS. Create a certificate "
        "with `python tools/generate_hub_certificate.py --host <this hub's LAN IP>`, then set "
        "hub.tls_certfile and hub.tls_keyfile in config.toml (or VRT_HUB__TLS_CERTFILE / "
        "VRT_HUB__TLS_KEYFILE). For a disposable test setup only, hub.allow_insecure_http = true."
    )


def main() -> None:
    """Entry point for the ``vrtelemetry-hub`` console script.

    The hub had no documented way to start it: no ``__main__`` block, no script,
    and no mention in any README. Everyone who ran it reconstructed a uvicorn
    command line from memory, which is how a service ends up bound to a
    different interface or port on every machine it runs on.

    Host and port come from :class:`~src.config.settings.HubSettings` --
    ``VRT_HUB__HOST`` / ``VRT_HUB__PORT``, or a ``[hub]`` block in
    ``config.toml``. The defaults bind all interfaces on 9000, because this is a
    LAN service other machines must reach, unlike the workstation's own API,
    which correctly binds loopback only.

    This docstring used to end "Replaced by typed settings in VRT-6", and it was
    not: the body went on reading ``VRT_HUB_HOST`` and ``VRT_HUB_PORT`` with a
    *single* underscore, which is not what pydantic-settings binds and not what
    ``config.example.toml`` or the port-collision error message tell you to set.
    So the documented way to move the hub silently did nothing, and the way that
    worked was documented nowhere. Both now work, and the old spelling says so.
    """
    import uvicorn

    host, port = resolve_bind_address()
    try:
        tls = resolve_tls(host)
    except HubTlsNotConfiguredError as exc:
        logger.error(str(exc))
        raise SystemExit(2) from exc
    scheme = "https" if tls else "http"

    logger.info(f"Starting VRTelemetry central hub on {scheme}://{host}:{port}")
    logger.info(f"  admin UI:     {scheme}://{host}:{port}/admin-ui")
    logger.info(f"  health check: {scheme}://{host}:{port}/health")
    uvicorn.run(app, host=host, port=port, log_level="info", **tls)


if __name__ == "__main__":
    main()
