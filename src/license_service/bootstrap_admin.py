"""Create or promote the hub's first administrator.

Run this **on the hub machine**, once, before anyone tries to open the admin UI.

Why it exists
-------------
``POST /auth/register`` always creates a ``researcher`` -- deliberately, so that
role escalation cannot happen through self-registration. The only way to become
an admin is ``POST /admin/users/set-role``, which is gated behind
``require_admin``. On a fresh install there is no admin, so over HTTP nothing
can create one: the admin UI cannot be opened, no licence can be issued, and no
workstation can activate. This is the deliberately manual step out of that, and
it is never exposed as an endpoint.

What changed here (VRT-25)
--------------------------
An earlier version of this module did the same job through four ``input()``
prompts. That is fine at a keyboard and unusable anywhere else: it cannot run
from a provisioning script, it cannot be tested, it returns 0 whether or not the
account was created, and it can only ever *create* -- an operator who had
already registered through the UI, which is the common case, had no way forward.

So: flags with a prompt only for the password, a promote path for an account
that already exists, real exit codes, idempotence, and
``tests/unit/test_bootstrap_admin.py``. The schema is initialised here too, so
this can genuinely be the first thing anyone runs on a new hub.

Usage::

    vrtelemetry-bootstrap-admin --email you@lab.org --org "Your Lab"
    python -m src.license_service.bootstrap_admin --email you@lab.org --org "Your Lab"

If the account exists it is promoted. If it does not, it is created as an admin
and you are prompted for a password (or pass ``--password``, which is visible in
your shell history -- prefer the prompt).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.license_service.auth_manager import AuthManager
from src.license_service.db_schema import initialize_license_schema


def _existing_user(auth: AuthManager, email: str) -> dict[str, Any] | None:
    """The account with this email, or None.

    Goes through :meth:`AuthManager.list_users` rather than opening the database
    here. ``test_no_module_outside_persistence_imports_sqlite3`` exists to keep
    SQL in the layer that owns it, and a convenience lookup is not a good reason
    to make an exception -- it is a good reason to use the method that already
    answers the question.
    """
    return next((u for u in auth.list_users() if u["email"] == email), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True, help="The account to create or promote.")
    parser.add_argument("--org", default="", help="Organisation name (new accounts only).")
    parser.add_argument("--name", default="", help="Display name (new accounts only).")
    parser.add_argument(
        "--password",
        default=None,
        help="New accounts only. Omit to be prompted, which keeps it out of shell history.",
    )
    args = parser.parse_args(argv)

    email = args.email.strip().lower()
    db_path = Path(get_settings().paths.licenses_db)

    # Idempotent, and the reason this tool can be the very first thing anyone
    # runs. AuthManager.register() assumes the schema is already there, which is
    # true once the hub has started -- but requiring a hub start first would put
    # the admin UI in front of the admin who does not exist yet.
    initialize_license_schema(db_path)
    auth = AuthManager(db_path)

    print(f"Licence database: {db_path}")

    user = _existing_user(auth, email)
    if user is not None:
        if user["role"] == "admin":
            print(f"{email} is already an admin. Nothing to do.")
            return 0
        if not auth.set_role(user["user_id"], "admin"):
            print(f"Could not promote {email}.", file=sys.stderr)
            return 1
        print(f"Promoted {email} to admin.")
        return 0

    if not args.org:
        print(
            "--org is required when creating a new account (it names the organisation "
            "the account belongs to).",
            file=sys.stderr,
        )
        return 2

    password = args.password or getpass.getpass(f"Password for {email} (min 8 chars): ")
    result = auth.register(email, password, args.org, args.name, role="admin")
    if not result.get("ok"):
        print(f"Could not create {email}: {result.get('reason')}", file=sys.stderr)
        return 1

    print(f"Created {email} as an admin of {args.org!r}.")
    print("Log in at http://<hub-host>:9000/admin-ui/ to issue licence keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
