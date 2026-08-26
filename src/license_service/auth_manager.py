# src/license_service/auth_manager.py

import sqlite3
import hashlib
import secrets
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 200_000
SESSION_LIFETIME_HOURS = 12

class AuthManager:
    """
    Account authentication for the central hub server. Deliberately separate
    from LicenseManager's activation/seat logic — this answers "who is this
    person", licensing answers "is this machine allowed to run right now."
    """

    def __init__(self, db_path: str = "LicenseServer/licenses.db"):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, email: str, password: str, org_name: str,
                 display_name: str = "", role: str = "researcher") -> Dict[str, Any]:
        email = email.strip().lower()
        if not email or "@" not in email:
            return {"ok": False, "reason": "invalid_email"}
        if len(password) < 8:
            return {"ok": False, "reason": "password_too_short"}
        if role not in ("researcher", "admin"):
            return {"ok": False, "reason": "invalid_role"}

        with self._conn() as conn:
            existing = conn.execute("SELECT user_id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                return {"ok": False, "reason": "email_already_registered"}

            org_id = self._get_or_create_org(conn, org_name)
            user_id = str(uuid.uuid4())
            salt = secrets.token_hex(16)
            pw_hash = self._hash_password(password, salt)

            conn.execute(
                """INSERT INTO users (user_id, org_id, email, password_hash, password_salt, display_name, role)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, org_id, email, pw_hash, salt, display_name, role)
            )
            conn.commit()

        logger.info(f"Registered new account: {email} (org={org_name}, role={role})")
        return {"ok": True, "user_id": user_id, "email": email, "role": role}

    def login(self, email: str, password: str) -> Dict[str, Any]:
        email = email.strip().lower()

        with self._conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if not user or not user["password_hash"]:
                return {"ok": False, "reason": "invalid_credentials"}

            expected_hash = self._hash_password(password, user["password_salt"])
            if not secrets.compare_digest(expected_hash, user["password_hash"]):
                return {"ok": False, "reason": "invalid_credentials"}

            session_token = secrets.token_urlsafe(32)
            expires_at = (datetime.utcnow() + timedelta(hours=SESSION_LIFETIME_HOURS)).isoformat()

            conn.execute(
                "INSERT INTO sessions (session_token, user_id, expires_at) VALUES (?, ?, ?)",
                (session_token, user["user_id"], expires_at)
            )
            conn.commit()

        logger.info(f"Login success: {email}")
        return {
            "ok": True,
            "session_token": session_token,
            "user_id": user["user_id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "role": user["role"],
            "expires_at": expires_at,
        }

    def validate_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT s.*, u.email, u.display_name, u.org_id, u.role
                   FROM sessions s JOIN users u ON s.user_id = u.user_id
                   WHERE s.session_token = ?""",
                (session_token,)
            ).fetchone()

            if not row or row["revoked"]:
                return None
            if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                return None

            return {
                "user_id": row["user_id"],
                "email": row["email"],
                "display_name": row["display_name"],
                "org_id": row["org_id"],
                "role": row["role"],
            }

    def logout(self, session_token: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET revoked = 1 WHERE session_token = ?", (session_token,))
            conn.commit()

    def is_admin(self, session_token: str) -> bool:
        session = self.validate_session(session_token)
        return bool(session and session["role"] == "admin")

    def set_role(self, target_user_id: str, role: str) -> bool:
        """Admin action: promote/demote another account. Enforced role check happens at the route layer."""
        if role not in ("researcher", "admin"):
            return False
        with self._conn() as conn:
            cur = conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, target_user_id))
            conn.commit()
            return cur.rowcount > 0

    def list_users(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT u.user_id, u.email, u.display_name, u.role, u.created_at, o.name AS org_name
                   FROM users u LEFT JOIN organizations o ON u.org_id = o.org_id
                   ORDER BY u.created_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def _get_or_create_org(self, conn: sqlite3.Connection, org_name: str) -> str:
        row = conn.execute("SELECT org_id FROM organizations WHERE name = ?", (org_name,)).fetchone()
        if row:
            return row["org_id"]
        org_id = str(uuid.uuid4())
        conn.execute("INSERT INTO organizations (org_id, name) VALUES (?, ?)", (org_id, org_name))
        return org_id

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
        ).hex()