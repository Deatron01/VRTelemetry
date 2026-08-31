# src/license_service/manager.py

import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import get_settings

logger = logging.getLogger(__name__)


class LicenseManager:
    """
    Server-side authority for issuing, validating, and revoking licenses.
    This runs on YOUR infrastructure — never bundled into the researcher's
    desktop app. The desktop app only ever talks to this over HTTPS.
    """

    def __init__(self, db_path: str | Path | None = None):
        # Resolved at call time, not as a default argument: a default is
        # evaluated once at import and would freeze the path before any
        # configuration could be read. See src/config/settings.py (VRT-6).
        self.db_path = Path(db_path) if db_path else get_settings().paths.licenses_db

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_license(
        self,
        email: str,
        org_name: str,
        plan: str = "standard",
        max_seats: int = 1,
        expires_in_days: int | None = 365,
    ) -> dict[str, Any]:
        """Admin action: issue a new license to a researcher/lab."""
        license_key = self._generate_license_key()
        license_id = str(uuid.uuid4())
        expires_at = (
            (datetime.utcnow() + timedelta(days=expires_in_days)).isoformat()
            if expires_in_days
            else None
        )

        with self._conn() as conn:
            org_id = self._get_or_create_org(conn, org_name)
            user_id = self._get_or_create_user(conn, email, org_id)

            conn.execute(
                """INSERT INTO licenses (license_id, license_key, user_id, org_id, plan, max_seats, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (license_id, license_key, user_id, org_id, plan, max_seats, expires_at),
            )
            conn.commit()

        logger.info(f"Issued license {license_key} to {email} ({max_seats} seats, plan={plan})")
        return {"license_id": license_id, "license_key": license_key, "expires_at": expires_at}

    def activate(
        self,
        license_key: str,
        hardware_fingerprint: str,
        machine_label: str,
        os_platform: str,
        app_version: str,
        ip_address: str = "",
    ) -> dict[str, Any]:
        """
        Called by the desktop app on first run / re-activation.
        Enforces seat limits and license validity before binding a machine.
        """
        with self._conn() as conn:
            lic = conn.execute(
                "SELECT * FROM licenses WHERE license_key = ?", (license_key,)
            ).fetchone()

            if not lic:
                self._log_event(conn, None, None, "reject", "unknown license key", ip_address)
                return {"ok": False, "reason": "invalid_license_key"}

            if lic["status"] != "active":
                self._log_event(
                    conn,
                    lic["license_id"],
                    None,
                    "reject",
                    f"license status={lic['status']}",
                    ip_address,
                )
                return {"ok": False, "reason": lic["status"]}

            if lic["expires_at"] and datetime.fromisoformat(lic["expires_at"]) < datetime.utcnow():
                self._log_event(conn, lic["license_id"], None, "reject", "expired", ip_address)
                return {"ok": False, "reason": "expired"}

            existing = conn.execute(
                """SELECT * FROM machine_activations
                   WHERE license_id = ? AND hardware_fingerprint = ? AND deactivated_at IS NULL""",
                (lic["license_id"], hardware_fingerprint),
            ).fetchone()

            if existing:
                if existing["is_revoked"]:
                    return {"ok": False, "reason": "machine_revoked"}
                conn.execute(
                    "UPDATE machine_activations SET last_heartbeat_at = CURRENT_TIMESTAMP WHERE activation_id = ?",
                    (existing["activation_id"],),
                )
                conn.commit()
                return {
                    "ok": True,
                    "activation_id": existing["activation_id"],
                    "expires_at": lic["expires_at"],
                    "license_id": lic["license_id"],
                }

            active_seats = conn.execute(
                """SELECT COUNT(*) FROM machine_activations
                   WHERE license_id = ? AND deactivated_at IS NULL AND is_revoked = 0""",
                (lic["license_id"],),
            ).fetchone()[0]

            if active_seats >= lic["max_seats"]:
                self._log_event(
                    conn, lic["license_id"], None, "reject", "seat_limit_reached", ip_address
                )
                return {"ok": False, "reason": "seat_limit_reached"}

            activation_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO machine_activations
                   (activation_id, license_id, hardware_fingerprint, machine_label, os_platform, app_version, last_heartbeat_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    activation_id,
                    lic["license_id"],
                    hardware_fingerprint,
                    machine_label,
                    os_platform,
                    app_version,
                ),
            )
            self._log_event(
                conn, lic["license_id"], activation_id, "activate", machine_label, ip_address
            )
            conn.commit()

            return {
                "ok": True,
                "activation_id": activation_id,
                "expires_at": lic["expires_at"],
                "license_id": lic["license_id"],
            }

    def heartbeat(
        self, activation_id: str, ip_address: str = "", machine_label: str | None = None
    ) -> dict[str, Any]:
        """
        Periodic check-in from a running desktop app. This is the mechanism
        that makes revocation actually take effect on a machine that's already
        activated. Also doubles as the keep-alive for the license/machine
        table's last_heartbeat_at column, which the Active Clients admin view
        falls back to when a client hasn't reported to /client/heartbeat yet.
        Passing machine_label keeps it current if the researcher renames the
        machine after activation; omit it (None) to leave it untouched.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT ma.*, l.status AS license_status, l.expires_at
                   FROM machine_activations ma
                   JOIN licenses l ON ma.license_id = l.license_id
                   WHERE ma.activation_id = ?""",
                (activation_id,),
            ).fetchone()

            if not row:
                return {"ok": False, "reason": "unknown_activation"}
            if row["is_revoked"] or row["deactivated_at"]:
                return {"ok": False, "reason": "machine_revoked"}
            if row["license_status"] != "active":
                return {"ok": False, "reason": row["license_status"]}
            if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                return {"ok": False, "reason": "expired"}

            if machine_label:
                conn.execute(
                    "UPDATE machine_activations SET last_heartbeat_at = CURRENT_TIMESTAMP, "
                    "machine_label = ? WHERE activation_id = ?",
                    (machine_label, activation_id),
                )
            else:
                conn.execute(
                    "UPDATE machine_activations SET last_heartbeat_at = CURRENT_TIMESTAMP WHERE activation_id = ?",
                    (activation_id,),
                )
            self._log_event(conn, row["license_id"], activation_id, "heartbeat", "", ip_address)
            conn.commit()

            return {"ok": True, "expires_at": row["expires_at"], "license_id": row["license_id"]}

    def revoke_license(self, license_key: str, reason: str = "") -> bool:
        """Admin action: kill an entire license (all machines) — your 'cut off a researcher' button."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE licenses SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP, revoked_reason = ? WHERE license_key = ?",
                (reason, license_key),
            )
            conn.commit()
            if cur.rowcount:
                lic = conn.execute(
                    "SELECT license_id FROM licenses WHERE license_key = ?", (license_key,)
                ).fetchone()
                self._log_event(conn, lic["license_id"], None, "revoke", reason, "")
                conn.commit()
                logger.warning(f"License {license_key} revoked: {reason}")
            return cur.rowcount > 0

    def revoke_machine(self, activation_id: str, reason: str = "") -> bool:
        """Admin action: kill one machine's seat without touching the rest of the license."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE machine_activations SET is_revoked = 1 WHERE activation_id = ?",
                (activation_id,),
            )
            conn.commit()
            if cur.rowcount:
                self._log_event(conn, None, activation_id, "revoke", reason, "")
                conn.commit()
            return cur.rowcount > 0

    def _get_or_create_org(self, conn: sqlite3.Connection, org_name: str) -> str:
        row = conn.execute(
            "SELECT org_id FROM organizations WHERE name = ?", (org_name,)
        ).fetchone()
        if row:
            return row["org_id"]
        org_id = str(uuid.uuid4())
        conn.execute("INSERT INTO organizations (org_id, name) VALUES (?, ?)", (org_id, org_name))
        return org_id

    def _get_or_create_user(self, conn: sqlite3.Connection, email: str, org_id: str) -> str:
        row = conn.execute("SELECT user_id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            return row["user_id"]
        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (user_id, org_id, email) VALUES (?, ?, ?)", (user_id, org_id, email)
        )
        return user_id

    def _log_event(self, conn, license_id, activation_id, event_type, detail, ip_address):
        conn.execute(
            """INSERT INTO activation_events (license_id, activation_id, event_type, detail, ip_address)
               VALUES (?, ?, ?, ?, ?)""",
            (license_id, activation_id, event_type, detail, ip_address),
        )

    def list_activations(self) -> list[dict[str, Any]]:
        """
        Every machine ever activated against any license, with enough license/
        org/owner context joined in that the admin Active Clients view doesn't
        need a second round trip. Used together with CentralDataManager's
        client_heartbeats table (which has the richer, more frequent presence
        data) — this is the fallback/enrichment source for machines that were
        activated but haven't sent a /client/heartbeat ping yet.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT ma.*, l.license_key, l.status AS license_status, l.plan,
                          l.expires_at AS license_expires_at,
                          u.email AS owner_email, o.name AS org_name
                   FROM machine_activations ma
                   JOIN licenses l ON ma.license_id = l.license_id
                   LEFT JOIN users u ON l.user_id = u.user_id
                   LEFT JOIN organizations o ON l.org_id = o.org_id
                   ORDER BY ma.last_heartbeat_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def list_licenses(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT l.*, u.email AS owner_email, o.name AS org_name,
                          (SELECT COUNT(*) FROM machine_activations ma
                           WHERE ma.license_id = l.license_id AND ma.deactivated_at IS NULL AND ma.is_revoked = 0
                          ) AS active_seats
                   FROM licenses l
                   LEFT JOIN users u ON l.user_id = u.user_id
                   LEFT JOIN organizations o ON l.org_id = o.org_id
                   ORDER BY l.issued_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def extend_license(self, license_key: str, additional_days: int) -> dict[str, Any]:
        """
        Admin action: pushes a license's expiry further out. If the license currently
        has no expiry (perpetual), this sets one starting from now — deliberate, since
        extending a "never expires" license doesn't make sense; that's a separate toggle.
        If it's already expired, extends from now rather than from the old expiry date,
        so re-activating a lapsed license doesn't require guessing math.
        """
        with self._conn() as conn:
            lic = conn.execute(
                "SELECT * FROM licenses WHERE license_key = ?", (license_key,)
            ).fetchone()
            if not lic:
                return {"ok": False, "reason": "license_not_found"}

            current_expiry = (
                datetime.fromisoformat(lic["expires_at"]) if lic["expires_at"] else None
            )
            base = (
                current_expiry
                if (current_expiry and current_expiry > datetime.utcnow())
                else datetime.utcnow()
            )
            new_expiry = base + timedelta(days=additional_days)

            conn.execute(
                "UPDATE licenses SET expires_at = ?, status = CASE WHEN status = 'expired' THEN 'active' ELSE status END WHERE license_key = ?",
                (new_expiry.isoformat(), license_key),
            )
            conn.commit()

            self._log_event(
                conn,
                lic["license_id"],
                None,
                "extend",
                f"+{additional_days} days, new expiry {new_expiry.isoformat()}",
                "",
            )
            conn.commit()

        logger.info(
            f"License {license_key} extended by {additional_days} days, new expiry {new_expiry.isoformat()}"
        )
        return {"ok": True, "new_expires_at": new_expiry.isoformat()}

    @staticmethod
    def _generate_license_key() -> str:
        import secrets

        groups = [secrets.token_hex(4).upper() for _ in range(4)]
        return "-".join(groups)
