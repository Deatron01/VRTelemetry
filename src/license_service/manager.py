# src/license_service/manager.py

import sqlite3
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class LicenseManager:
    """
    Server-side authority for issuing, validating, and revoking licenses.
    This runs on YOUR infrastructure — never bundled into the researcher's
    desktop app. The desktop app only ever talks to this over HTTPS.
    """

    def __init__(self, db_path: str = "LicenseServer/licenses.db"):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_license(self, email: str, org_name: str, plan: str = "standard",
                        max_seats: int = 1, expires_in_days: Optional[int] = 365) -> Dict[str, Any]:
        """Admin action: issue a new license to a researcher/lab."""
        license_key = self._generate_license_key()
        license_id = str(uuid.uuid4())
        expires_at = (
            (datetime.utcnow() + timedelta(days=expires_in_days)).isoformat()
            if expires_in_days else None
        )

        with self._conn() as conn:
            org_id = self._get_or_create_org(conn, org_name)
            user_id = self._get_or_create_user(conn, email, org_id)

            conn.execute(
                """INSERT INTO licenses (license_id, license_key, user_id, org_id, plan, max_seats, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (license_id, license_key, user_id, org_id, plan, max_seats, expires_at)
            )
            conn.commit()

        logger.info(f"Issued license {license_key} to {email} ({max_seats} seats, plan={plan})")
        return {"license_id": license_id, "license_key": license_key, "expires_at": expires_at}

    def activate(self, license_key: str, hardware_fingerprint: str,
                 machine_label: str, os_platform: str, app_version: str,
                 ip_address: str = "") -> Dict[str, Any]:
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
                self._log_event(conn, lic["license_id"], None, "reject", f"license status={lic['status']}", ip_address)
                return {"ok": False, "reason": lic["status"]}

            if lic["expires_at"] and datetime.fromisoformat(lic["expires_at"]) < datetime.utcnow():
                self._log_event(conn, lic["license_id"], None, "reject", "expired", ip_address)
                return {"ok": False, "reason": "expired"}

            existing = conn.execute(
                """SELECT * FROM machine_activations
                   WHERE license_id = ? AND hardware_fingerprint = ? AND deactivated_at IS NULL""",
                (lic["license_id"], hardware_fingerprint)
            ).fetchone()

            if existing:
                if existing["is_revoked"]:
                    return {"ok": False, "reason": "machine_revoked"}
                conn.execute(
                    "UPDATE machine_activations SET last_heartbeat_at = CURRENT_TIMESTAMP WHERE activation_id = ?",
                    (existing["activation_id"],)
                )
                conn.commit()
                return {"ok": True, "activation_id": existing["activation_id"], "expires_at": lic["expires_at"]}

            active_seats = conn.execute(
                """SELECT COUNT(*) FROM machine_activations
                   WHERE license_id = ? AND deactivated_at IS NULL AND is_revoked = 0""",
                (lic["license_id"],)
            ).fetchone()[0]

            if active_seats >= lic["max_seats"]:
                self._log_event(conn, lic["license_id"], None, "reject", "seat_limit_reached", ip_address)
                return {"ok": False, "reason": "seat_limit_reached"}

            activation_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO machine_activations
                   (activation_id, license_id, hardware_fingerprint, machine_label, os_platform, app_version, last_heartbeat_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (activation_id, lic["license_id"], hardware_fingerprint, machine_label, os_platform, app_version)
            )
            self._log_event(conn, lic["license_id"], activation_id, "activate", machine_label, ip_address)
            conn.commit()

            return {"ok": True, "activation_id": activation_id, "expires_at": lic["expires_at"]}

    def heartbeat(self, activation_id: str, ip_address: str = "") -> Dict[str, Any]:
        """
        Periodic check-in from a running desktop app. This is the mechanism
        that makes revocation actually take effect on a machine that's already activated.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT ma.*, l.status AS license_status, l.expires_at
                   FROM machine_activations ma
                   JOIN licenses l ON ma.license_id = l.license_id
                   WHERE ma.activation_id = ?""",
                (activation_id,)
            ).fetchone()

            if not row:
                return {"ok": False, "reason": "unknown_activation"}
            if row["is_revoked"] or row["deactivated_at"]:
                return {"ok": False, "reason": "machine_revoked"}
            if row["license_status"] != "active":
                return {"ok": False, "reason": row["license_status"]}
            if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                return {"ok": False, "reason": "expired"}

            conn.execute(
                "UPDATE machine_activations SET last_heartbeat_at = CURRENT_TIMESTAMP WHERE activation_id = ?",
                (activation_id,)
            )
            self._log_event(conn, row["license_id"], activation_id, "heartbeat", "", ip_address)
            conn.commit()

            return {"ok": True, "expires_at": row["expires_at"]}

    def revoke_license(self, license_key: str, reason: str = "") -> bool:
        """Admin action: kill an entire license (all machines) — your 'cut off a researcher' button."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE licenses SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP, revoked_reason = ? WHERE license_key = ?",
                (reason, license_key)
            )
            conn.commit()
            if cur.rowcount:
                lic = conn.execute("SELECT license_id FROM licenses WHERE license_key = ?", (license_key,)).fetchone()
                self._log_event(conn, lic["license_id"], None, "revoke", reason, "")
                conn.commit()
                logger.warning(f"License {license_key} revoked: {reason}")
            return cur.rowcount > 0

    def revoke_machine(self, activation_id: str, reason: str = "") -> bool:
        """Admin action: kill one machine's seat without touching the rest of the license."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE machine_activations SET is_revoked = 1 WHERE activation_id = ?",
                (activation_id,)
            )
            conn.commit()
            if cur.rowcount:
                self._log_event(conn, None, activation_id, "revoke", reason, "")
                conn.commit()
            return cur.rowcount > 0

    def _get_or_create_org(self, conn: sqlite3.Connection, org_name: str) -> str:
        row = conn.execute("SELECT org_id FROM organizations WHERE name = ?", (org_name,)).fetchone()
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
        conn.execute("INSERT INTO users (user_id, org_id, email) VALUES (?, ?, ?)", (user_id, org_id, email))
        return user_id

    def _log_event(self, conn, license_id, activation_id, event_type, detail, ip_address):
        conn.execute(
            """INSERT INTO activation_events (license_id, activation_id, event_type, detail, ip_address)
               VALUES (?, ?, ?, ?, ?)""",
            (license_id, activation_id, event_type, detail, ip_address)
        )

    @staticmethod
    def _generate_license_key() -> str:
        import secrets
        groups = [secrets.token_hex(4).upper() for _ in range(4)]
        return "-".join(groups)